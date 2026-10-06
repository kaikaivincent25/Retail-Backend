from datetime import date, date as date_type, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_cashier
from app.core.database import get_db
from app.models.sale import Sale
from app.models.user import User
from app.schemas.sale import SaleCreate, SaleRead
from app.services.cash_sessions import get_open_session
from app.services.sales import SaleError, complete_sale

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