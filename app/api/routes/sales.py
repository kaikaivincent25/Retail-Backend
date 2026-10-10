from datetime import date, date as date_type, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_cashier, require_manager
from app.core.database import get_db
from app.models.sale import PaymentMethod, Sale, SaleStatus
from app.models.shop import Shop
from app.models.user import User
from app.schemas.sale import (
    ManualMpesaSaleCreate,
    ManualPaymentConfirm,
    MpesaSaleCreate,
    MpesaReconciliationRead,
    SaleCreate,
    SaleRead,
)
from app.services.cash_sessions import get_open_session
from app.services.mpesa import (
    MpesaConfigurationError,
    MpesaRequestError,
    ensure_mpesa_configured,
    normalize_phone_number,
    process_stk_callback,
    query_stk_status,
    request_stk_push,
    StkQueryStatus,
)
from app.services.sales import (
    SaleError,
    apply_stk_reconciliation,
    confirm_manual_payment,
    complete_sale,
    create_pending_manual_sale,
    create_pending_mpesa_sale,
    release_pending_sale,
)

router = APIRouter(prefix="/sales", tags=["Sales"])


@router.post("", response_model=SaleRead, status_code=201)
def create_sale(
    payload: SaleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    session = get_open_session(db, user.shop_id, lock=True)
    if session is None:
        raise HTTPException(
            status_code=422,
            detail="You must open a cash session before making a sale",
        )

    try:
        sale = complete_sale(
            db,
            shop_id=user.shop_id,
            cashier_id=user.id,
            items=[item.model_dump() for item in payload.items],
            amount_received=payload.amount_received,
            payment_method=payload.payment_method,
            session_id=session.id,
        )
    except SaleError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return sale


@router.post("/mpesa", response_model=SaleRead, status_code=202)
def create_mpesa_sale(
    payload: MpesaSaleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    session = get_open_session(db, user.shop_id, lock=True)
    if session is None:
        raise HTTPException(
            status_code=422,
            detail="You must open a cash session before making a sale",
        )
    sale: Sale | None = None
    try:
        ensure_mpesa_configured()
        phone_number = normalize_phone_number(payload.phone_number)
        sale = create_pending_mpesa_sale(
            db,
            shop_id=user.shop_id,
            cashier_id=user.id,
            items=[item.model_dump() for item in payload.items],
            phone_number=phone_number,
            session_id=session.id,
        )
        identifiers = request_stk_push(sale.id, sale.total, phone_number)
        sale.mpesa_checkout_request_id = identifiers["checkout_request_id"]
        sale.mpesa_merchant_request_id = identifiers["merchant_request_id"]
        db.commit()
        db.refresh(sale)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SaleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MpesaConfigurationError as exc:
        if sale is not None:
            release_pending_sale(db, sale.id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MpesaRequestError as exc:
        if exc.definitive_rejection and sale is not None:
            release_pending_sale(db, sale.id)
        detail = str(exc)
        if not exc.definitive_rejection and sale is not None:
            detail = f"{detail} Pending sale #{sale.id} remains reserved; do not retry until checked."
        raise HTTPException(status_code=502, detail=detail) from exc

    return sale


@router.post("/manual-mpesa", response_model=SaleRead, status_code=202)
def create_manual_mpesa_sale(
    payload: ManualMpesaSaleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    session = get_open_session(db, user.shop_id, lock=True)
    if session is None:
        raise HTTPException(
            status_code=422,
            detail="You must open a cash session before making a sale",
        )

    shop = db.get(Shop, user.shop_id)
    destinations = {
        PaymentMethod.POCHI: (shop.mpesa_pochi_number, None),
        PaymentMethod.TILL: (shop.mpesa_till_number, None),
        PaymentMethod.PAYBILL: (
            shop.mpesa_paybill_number,
            shop.mpesa_paybill_account_number,
        ),
    }
    destination_number, account_number = destinations[payload.payment_method]
    if not destination_number or (
        payload.payment_method == PaymentMethod.PAYBILL and not account_number
    ):
        raise HTTPException(status_code=422, detail="This M-Pesa payment option is not configured")

    try:
        return create_pending_manual_sale(
            db,
            shop_id=user.shop_id,
            cashier_id=user.id,
            items=[item.model_dump() for item in payload.items],
            payment_method=payload.payment_method,
            destination_number=destination_number,
            account_number=account_number,
            session_id=session.id,
        )
    except SaleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{sale_id}/manual-payment/confirm", response_model=SaleRead)
def confirm_manual_mpesa_sale(
    sale_id: int,
    payload: ManualPaymentConfirm,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    sale = db.scalar(
        _sale_query_for_shop(user.shop_id).where(Sale.id == sale_id).with_for_update()
    )
    if sale is None or (user.role.value == "cashier" and sale.cashier_id != user.id):
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.status == SaleStatus.COMPLETED and sale.mpesa_receipt_number == payload.receipt_number:
        return sale
    try:
        return confirm_manual_payment(db, sale, payload.receipt_number, user.id)
    except SaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{sale_id}/manual-payment/cancel", response_model=SaleRead)
def cancel_manual_mpesa_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    sale = db.scalar(
        _sale_query_for_shop(user.shop_id).where(Sale.id == sale_id).with_for_update()
    )
    if sale is None or (user.role.value == "cashier" and sale.cashier_id != user.id):
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.payment_method not in {PaymentMethod.POCHI, PaymentMethod.TILL, PaymentMethod.PAYBILL}:
        raise HTTPException(status_code=409, detail="This sale is not a manual M-Pesa payment")
    if sale.status != SaleStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only a pending payment can be cancelled")
    cancelled = release_pending_sale(db, sale.id)
    return cancelled


@router.post("/mpesa/callback")
def mpesa_callback(payload: dict, db: Session = Depends(get_db)):
    try:
        processed = process_stk_callback(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ResultCode": 0,
        "ResultDesc": "Accepted" if processed else "Callback received for reconciliation",
    }


@router.post(
    "/{sale_id}/mpesa/reconcile",
    response_model=MpesaReconciliationRead,
)
def reconcile_mpesa_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    sale = db.scalar(
        _sale_query_for_shop(user.shop_id).where(Sale.id == sale_id)
    )
    if sale is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.payment_method != PaymentMethod.MPESA:
        raise HTTPException(status_code=409, detail="This sale is not an STK M-Pesa payment")
    if sale.status != SaleStatus.PENDING:
        outcome = sale.status.value
        return {
            "outcome": outcome,
            "message": "This payment has already been resolved.",
            "sale": sale,
        }
    if not sale.mpesa_checkout_request_id:
        raise HTTPException(
            status_code=409,
            detail="This payment has no Daraja checkout ID and requires manual review.",
        )

    try:
        provider_status = query_stk_status(sale.mpesa_checkout_request_id)
    except MpesaConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MpesaRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        updated_sale = apply_stk_reconciliation(
            db,
            sale.id,
            provider_status.value,
            reconciled_by_user_id=user.id,
        )
    except SaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    messages = {
        StkQueryStatus.COMPLETED: "Daraja confirmed the payment.",
        StkQueryStatus.FAILED: "Daraja confirmed the payment failed; reserved stock was released.",
        StkQueryStatus.PENDING: "Daraja has no definitive result; the sale remains pending and stock stays reserved.",
    }
    outcome = updated_sale.status.value
    message = (
        messages[provider_status]
        if outcome == provider_status.value
        else "A callback resolved this payment while the status query was running."
    )
    return {
        "outcome": outcome,
        "message": message,
        "sale": updated_sale,
    }


def _sale_query_for_shop(shop_id: int):
    return select(Sale).where(Sale.shop_id == shop_id).options(selectinload(Sale.items))


@router.get("", response_model=list[SaleRead])
def list_sales(
    cashier_id: int | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    query = _sale_query_for_shop(user.shop_id)

    # Cashiers only ever see their own history; managers/admins can filter by cashier_id
    if user.role.value == "cashier":
        query = query.where(Sale.cashier_id == user.id)
    elif cashier_id is not None:
        query = query.where(Sale.cashier_id == cashier_id)

    if start_date is not None:
        query = query.where(
            Sale.created_at >= datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        )
    if end_date is not None:
        query = query.where(
            Sale.created_at <= datetime.combine(end_date, time.max, tzinfo=timezone.utc)
        )

    query = query.order_by(Sale.created_at.desc()).offset(skip).limit(limit)
    return db.scalars(query).all()


@router.get("/today", response_model=list[SaleRead])
def sales_today(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    start = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    end = datetime.combine(date.today(), time.max, tzinfo=timezone.utc)

    query = _sale_query_for_shop(user.shop_id).where(
        Sale.created_at >= start, Sale.created_at <= end
    )
    query = query.order_by(Sale.created_at.desc())
    return db.scalars(query).all()


@router.get("/{sale_id}", response_model=SaleRead)
def get_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    query = _sale_query_for_shop(user.shop_id).where(Sale.id == sale_id)
    sale = db.scalar(query)

    if sale is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    if user.role.value == "cashier" and sale.cashier_id != user.id:
        raise HTTPException(status_code=404, detail="Sale not found")  # 404, not 403 — don't leak existence

    return sale