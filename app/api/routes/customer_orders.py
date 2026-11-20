import secrets
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_cashier
from app.core.database import get_db
from app.models.customer_order import (
    CustomerOrder,
    CustomerOrderEvent,
    CustomerOrderItem,
    CustomerOrderStatus,
    OrderFulfilment,
    OrderPaymentMethod,
    OrderPaymentStatus,
)
from app.models.customer import Customer
from app.models.product import Product
from app.models.shop import Shop
from app.models.user import User
from app.models.variant import Variant
from app.models.sale import PaymentMethod
from app.services.cash_sessions import get_open_session
from app.services.order_reservations import (
    active_reserved_quantity,
    consume_order_reservations,
    expire_reservations,
    release_order_reservations,
    reserve_order,
)
from app.services.sales import SaleError, complete_sale
from app.services.mpesa import (
    MpesaConfigurationError,
    MpesaRequestError,
    normalize_phone_number,
    query_stk_status,
    request_stk_push_for_reference,
    StkQueryStatus,
)
from app.models.activity_log import ActivityAction
from app.services.audit import log_activity
from app.services.notifications import queue_order_notification
from app.services.customer_identity import normalize_customer_phone
from app.services.billing import require_feature
from app.schemas.customer_order import (
    CustomerOrderCreate,
    CustomerOrderRead,
    CustomerOrderStatusUpdate,
    CustomerOrderPaymentRecord,
    CustomerOrderEventRead,
    PublicOrderRead,
    PublicOrderTrackingRead,
)

public_router = APIRouter(prefix="/public", tags=["Customer orders"])
private_router = APIRouter(prefix="/orders", tags=["Customer orders"])
TRACKING_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TRACKING_CODE_LENGTH = 12


def _get_public_shop(db: Session, slug: str) -> Shop:
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_suspended.is_(False)))
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    require_feature(db, shop.id, "online_store")
    return shop


def _order_query(order_id: int | None = None):
    query = select(CustomerOrder).options(selectinload(CustomerOrder.items))
    if order_id is not None:
        query = query.where(CustomerOrder.id == order_id)
    return query


def _record_order_event(
    db: Session,
    order: CustomerOrder,
    event_type: str,
    actor_user_id: int | None,
    from_status: CustomerOrderStatus | None = None,
    to_status: CustomerOrderStatus | None = None,
    details: str | None = None,
) -> None:
    db.add(
        CustomerOrderEvent(
            order_id=order.id,
            shop_id=order.shop_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            from_status=from_status.value if from_status else None,
            to_status=to_status.value if to_status else None,
            details=details,
        )
    )


def _public_order(order: CustomerOrder) -> PublicOrderRead:
    return PublicOrderRead(
        public_token=order.public_token,
        tracking_code=order.tracking_code,
        order_number=order.order_number,
        status=order.status,
        fulfilment=order.fulfilment,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        mpesa_receipt_number=order.mpesa_receipt_number,
        customer_name=order.customer_name,
        subtotal=order.subtotal,
        total=order.total,
        items=order.items,
        created_at=order.created_at,
    )


def _new_tracking_code(db: Session) -> str:
    while True:
        code = "".join(
            secrets.choice(TRACKING_CODE_ALPHABET)
            for _ in range(TRACKING_CODE_LENGTH)
        )
        if db.scalar(select(CustomerOrder.id).where(CustomerOrder.tracking_code == code)) is None:
            return code


def _order_number(shop: Shop, order_id: int) -> str:
    prefix = re.sub(r"[^A-Z0-9]", "", (shop.slug or shop.name).upper())[:2] or "SH"
    return f"{prefix}-{1000 + order_id}"


def _pending_order_number(shop: Shop) -> str:
    """Return a valid number for the initial INSERT before the database assigns an id."""
    prefix = re.sub(r"[^A-Z0-9]", "", (shop.slug or shop.name).upper())[:2] or "SH"
    return f"{prefix}-P{secrets.token_hex(5).upper()}"


@public_router.post("/shops/{slug}/orders", response_model=PublicOrderRead, status_code=status.HTTP_201_CREATED)
def create_customer_order(slug: str, payload: CustomerOrderCreate, db: Session = Depends(get_db)):
    expire_reservations(db)
    shop = _get_public_shop(db, slug)
    variant_ids = [item.variant_id for item in payload.items]
    variants = db.scalars(
        select(Variant)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Variant.id.in_(variant_ids),
            Variant.is_active.is_(True),
            Product.shop_id == shop.id,
            Product.is_active.is_(True),
            Product.is_public.is_(True),
        )
    ).all()
    by_id = {variant.id: variant for variant in variants}
    if len(by_id) != len(variant_ids):
        raise HTTPException(status_code=422, detail="One or more selected products are no longer available")

    subtotal = Decimal("0.00")
    items = []
    for requested in payload.items:
        variant = by_id[requested.variant_id]
        available = variant.quantity - active_reserved_quantity(db, variant.id)
        if requested.quantity > available:
            raise HTTPException(status_code=409, detail=f"Only {available} of '{variant.name}' are available")
        line_total = variant.selling_price * requested.quantity
        subtotal += line_total
        items.append(CustomerOrderItem(
            variant_id=variant.id,
            variant_name=variant.name,
            quantity=requested.quantity,
            unit_price=variant.selling_price,
            line_total=line_total,
        ))

    public_token = secrets.token_urlsafe(32)
    normalized_phone = normalize_customer_phone(payload.customer_phone)
    matched_customers = (
        db.scalars(
            select(Customer).where(
                Customer.shop_id == shop.id,
                Customer.phone_normalized == normalized_phone,
                Customer.is_active.is_(True),
            ).order_by(Customer.id)
        ).all()
        if normalized_phone
        else []
    )
    identity_review_required = len(matched_customers) > 1
    if len(matched_customers) == 1:
        customer = matched_customers[0]
    else:
        customer = Customer(
            shop_id=shop.id,
            full_name=payload.customer_name.strip(),
            phone=payload.customer_phone.strip(),
            phone_normalized=normalized_phone,
            identity_review_required=identity_review_required,
        )
        db.add(customer)
        db.flush()
    order = CustomerOrder(
        shop_id=shop.id,
        # order_number is non-null, but the final human-readable number uses
        # the database id. Insert a short unique placeholder first, then
        # replace it once the id has been allocated.
        order_number=_pending_order_number(shop),
        public_token=public_token,
        tracking_code=_new_tracking_code(db),
        fulfilment=payload.fulfilment,
        payment_method=payload.payment_method,
        customer_name=payload.customer_name.strip(),
        customer_phone=payload.customer_phone.strip(),
        customer_phone_normalized=normalized_phone,
        customer_id=customer.id,
        delivery_address=payload.delivery_address.strip() if payload.delivery_address else None,
        estate=payload.estate.strip() if payload.estate else None,
        landmark=payload.landmark.strip() if payload.landmark else None,
        delivery_instructions=payload.delivery_instructions.strip() if payload.delivery_instructions else None,
        preferred_delivery_time=payload.preferred_delivery_time.strip() if payload.preferred_delivery_time else None,
        subtotal=subtotal,
        total=subtotal,
        items=items,
    )
    db.add(order)
    db.flush()
    order.order_number = _order_number(shop, order.id)
    _record_order_event(
        db,
        order,
        "order_placed",
        None,
        to_status=CustomerOrderStatus.PENDING,
        details=(
            "Customer profile needs identity review because multiple active profiles "
            "share this phone number."
            if identity_review_required
            else "Order submitted through the public shop."
        ),
    )
    queue_order_notification(
        db,
        order,
        "order_submitted",
        f"{shop.name}: order {order.order_number} was received. We will confirm it shortly.",
    )
    db.commit()
    saved_order = db.scalar(_order_query(order.id))
    if saved_order is None:
        raise HTTPException(status_code=500, detail="The order was created but could not be loaded for confirmation")
    return _public_order(saved_order)


@public_router.get("/orders/track/{tracking_code}", response_model=PublicOrderTrackingRead)
def track_customer_order_by_code(tracking_code: str, db: Session = Depends(get_db)):
    normalized_code = re.sub(r"[\s-]", "", tracking_code).upper()
    if not re.fullmatch(r"[A-Z0-9]{12}", normalized_code):
        raise HTTPException(status_code=404, detail="Order not found")
    order = db.scalar(
        select(CustomerOrder).where(CustomerOrder.tracking_code == normalized_code)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return PublicOrderTrackingRead(
        order_number=order.order_number,
        status=order.status,
        fulfilment=order.fulfilment,
        payment_status=order.payment_status,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@public_router.get("/orders/{public_token}", response_model=PublicOrderRead)
def track_customer_order(public_token: str, db: Session = Depends(get_db)):
    order = db.scalar(_order_query(None).where(CustomerOrder.public_token == public_token))
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return _public_order(order)


@public_router.post("/orders/{public_token}/cancel", response_model=PublicOrderRead)
def cancel_public_order(public_token: str, db: Session = Depends(get_db)):
    order = db.scalar(
        _order_query(None)
        .where(CustomerOrder.public_token == public_token)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_status == OrderPaymentStatus.PAID:
        raise HTTPException(
            status_code=409,
            detail="This order has already been paid and cannot be cancelled online. Please contact the shop.",
        )
    if order.payment_status == OrderPaymentStatus.INITIATED:
        raise HTTPException(
            status_code=409,
            detail="An M-Pesa payment is still in progress. Wait for its result before cancelling.",
        )
    if order.status not in {CustomerOrderStatus.PENDING, CustomerOrderStatus.ACCEPTED}:
        raise HTTPException(
            status_code=409,
            detail="This order can no longer be cancelled online. Please contact the shop.",
        )

    previous_status = order.status
    order.status = CustomerOrderStatus.CANCELLED
    release_order_reservations(db, order.id, None)
    _record_order_event(
        db,
        order,
        "status_changed",
        None,
        from_status=previous_status,
        to_status=CustomerOrderStatus.CANCELLED,
        details="Customer cancelled the order through the public shop.",
    )
    queue_order_notification(
        db,
        order,
        "order_cancelled",
        f"{order.order_number} was cancelled by the customer.",
    )
    db.commit()
    return _public_order(db.scalar(_order_query(order.id)))


@private_router.get("", response_model=list[CustomerOrderRead])
def list_customer_orders(
    order_status: CustomerOrderStatus | None = Query(None, alias="status"),
    payment_status: OrderPaymentStatus | None = Query(None),
    search: str | None = Query(default=None, max_length=150),
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    expire_reservations(db)
    db.commit()
    query = _order_query(None).where(CustomerOrder.shop_id == user.shop_id)
    if order_status is not None:
        query = query.where(CustomerOrder.status == order_status)
    if payment_status is not None:
        query = query.where(CustomerOrder.payment_status == payment_status)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                CustomerOrder.order_number.ilike(term),
                CustomerOrder.customer_name.ilike(term),
                CustomerOrder.customer_phone.ilike(term),
            )
        )
    return db.scalars(query.order_by(CustomerOrder.created_at.desc()).limit(200)).all()


@private_router.patch("/{order_id}", response_model=CustomerOrderRead)
def update_customer_order(
    order_id: int,
    payload: CustomerOrderStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    order = db.scalar(_order_query(order_id).where(CustomerOrder.shop_id == user.shop_id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status in {CustomerOrderStatus.REJECTED, CustomerOrderStatus.CANCELLED, CustomerOrderStatus.COMPLETED}:
        raise HTTPException(status_code=409, detail="This order is already closed")
    allowed_transitions = {
        CustomerOrderStatus.PENDING: {CustomerOrderStatus.ACCEPTED, CustomerOrderStatus.REJECTED, CustomerOrderStatus.CANCELLED},
        CustomerOrderStatus.ACCEPTED: {CustomerOrderStatus.PREPARING, CustomerOrderStatus.CANCELLED},
        CustomerOrderStatus.PREPARING: {
            CustomerOrderStatus.READY_FOR_PICKUP,
            CustomerOrderStatus.OUT_FOR_DELIVERY,
            CustomerOrderStatus.CANCELLED,
        },
        CustomerOrderStatus.READY_FOR_PICKUP: {CustomerOrderStatus.DELIVERED, CustomerOrderStatus.CANCELLED},
        CustomerOrderStatus.OUT_FOR_DELIVERY: {CustomerOrderStatus.DELIVERED, CustomerOrderStatus.CANCELLED},
        CustomerOrderStatus.DELIVERED: {CustomerOrderStatus.COMPLETED},
    }
    if payload.status not in allowed_transitions.get(order.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot move an order from {order.status.value} to {payload.status.value}")
    if payload.status == CustomerOrderStatus.OUT_FOR_DELIVERY and order.fulfilment != OrderFulfilment.DELIVERY:
        raise HTTPException(status_code=409, detail="Pickup orders cannot be sent for delivery")
    if payload.status == CustomerOrderStatus.DELIVERED:
        recipient = (payload.received_by_name or "").strip()
        if not recipient:
            raise HTTPException(status_code=422, detail="Record who received or collected the order")
        order.received_by_name = recipient
    if (
        payload.status in {CustomerOrderStatus.REJECTED, CustomerOrderStatus.CANCELLED}
        and order.payment_status == OrderPaymentStatus.PAID
    ):
        raise HTTPException(
            status_code=409,
            detail="A paid order cannot be cancelled or rejected without recording a refund.",
        )
    if payload.status == CustomerOrderStatus.ACCEPTED:
        try:
            reserve_order(db, order, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if payload.status in {CustomerOrderStatus.REJECTED, CustomerOrderStatus.CANCELLED}:
        release_order_reservations(db, order.id, user.id)
    if payload.status == CustomerOrderStatus.COMPLETED:
        if order.payment_status != OrderPaymentStatus.PAID:
            raise HTTPException(status_code=409, detail="Record payment before closing this order")
        if order.sale_id is None:
            session = get_open_session(db, user.shop_id, lock=True)
            if session is None:
                raise HTTPException(status_code=422, detail="Open a cash session before completing an online order")
            try:
                sale = complete_sale(
                    db,
                    shop_id=user.shop_id,
                    cashier_id=user.id,
                    items=[{"variant_id": item.variant_id, "quantity": item.quantity} for item in order.items],
                    amount_received=order.total,
                    payment_method=(
                        PaymentMethod.MPESA
                        if order.payment_method == OrderPaymentMethod.MANUAL_MPESA
                        else PaymentMethod.CASH
                    ),
                    session_id=order.session_id or session.id,
                    customer_id=order.customer_id,
                    allow_confirmed_mpesa=order.payment_method == OrderPaymentMethod.MANUAL_MPESA,
                    created_at=order.paid_at,
                    commit=False,
                )
            except SaleError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            order.sale_id = sale.id
            consume_order_reservations(db, order.id)
    previous_status = order.status
    order.status = payload.status
    queue_order_notification(
        db,
        order,
        f"order_{payload.status.value}",
        f"{order.order_number} is now {payload.status.value.replace('_', ' ')}.",
    )
    if "shop_note" in payload.model_fields_set:
        order.shop_note = payload.shop_note
    _record_order_event(
        db,
        order,
        "status_changed",
        user.id,
        from_status=previous_status,
        to_status=order.status,
        details=(
            f"Received by {order.received_by_name}."
            if order.status == CustomerOrderStatus.DELIVERED
            else payload.shop_note
        ),
    )
    db.commit()
    db.refresh(order)
    return order


@public_router.post("/orders/{public_token}/mpesa", response_model=PublicOrderRead, status_code=202)
def initiate_order_mpesa(public_token: str, db: Session = Depends(get_db)):
    order = db.scalar(_order_query(None).where(CustomerOrder.public_token == public_token).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_method != OrderPaymentMethod.MANUAL_MPESA:
        raise HTTPException(status_code=409, detail="This order does not use M-Pesa")
    if order.payment_status == OrderPaymentStatus.PAID:
        return _public_order(order)
    if order.status not in {CustomerOrderStatus.PENDING, CustomerOrderStatus.ACCEPTED}:
        raise HTTPException(status_code=409, detail="This order can no longer receive payment")
    try:
        phone = normalize_phone_number(order.customer_phone)
        identifiers = request_stk_push_for_reference(
            reference=order.order_number,
            description=f"Order {order.order_number}",
            amount=order.total,
            phone_number=phone,
            callback_url=__import__("app.core.config", fromlist=["settings"]).settings.MPESA_CALLBACK_URL,
        )
    except (ValueError, MpesaConfigurationError, MpesaRequestError) as exc:
        order.payment_status = OrderPaymentStatus.FAILED
        _record_order_event(
            db,
            order,
            "payment_failed",
            None,
            details=f"M-Pesa payment could not be started: {exc}",
        )
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    order.payment_status = OrderPaymentStatus.INITIATED
    order.mpesa_phone_number = phone
    order.mpesa_checkout_request_id = identifiers["checkout_request_id"]
    order.mpesa_merchant_request_id = identifiers["merchant_request_id"]
    _record_order_event(
        db,
        order,
        "payment_initiated",
        None,
        details=f"M-Pesa payment initiated for {order.order_number}.",
    )
    db.commit()
    db.refresh(order)
    return _public_order(order)


@public_router.get("/orders/{public_token}/mpesa/status", response_model=PublicOrderRead)
def query_order_mpesa(public_token: str, db: Session = Depends(get_db)):
    order = db.scalar(_order_query(None).where(CustomerOrder.public_token == public_token))
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_status == OrderPaymentStatus.INITIATED and order.mpesa_checkout_request_id:
        try:
            result = query_stk_status(order.mpesa_checkout_request_id)
        except MpesaRequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if result == StkQueryStatus.FAILED:
            order.payment_status = OrderPaymentStatus.FAILED
            _record_order_event(
                db,
                order,
                "payment_failed",
                None,
                details=f"M-Pesa payment failed for {order.order_number}.",
            )
            db.commit()
        elif result == StkQueryStatus.COMPLETED:
            # The callback remains authoritative for the receipt and phone metadata.
            pass
    return _public_order(order)


@private_router.post("/{order_id}/payment/confirm", response_model=CustomerOrderRead)
def confirm_order_manual_payment(
    order_id: int,
    receipt_number: str = Query(..., min_length=1, max_length=30),
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    order = db.scalar(_order_query(order_id).where(CustomerOrder.shop_id == user.shop_id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_method != OrderPaymentMethod.MANUAL_MPESA:
        raise HTTPException(status_code=409, detail="This order does not use manual M-Pesa")
    if order.status in {CustomerOrderStatus.REJECTED, CustomerOrderStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="This order is already closed")
    receipt = receipt_number.strip()
    if order.payment_status == OrderPaymentStatus.PAID:
        if order.mpesa_receipt_number == receipt:
            return order
        raise HTTPException(status_code=409, detail="Payment has already been recorded")
    order.payment_status = OrderPaymentStatus.PAID
    order.mpesa_receipt_number = receipt
    order.payment_reference = receipt
    order.paid_at = datetime.now(timezone.utc)
    order.paid_by_user_id = user.id
    session = get_open_session(db, user.shop_id, lock=True)
    order.session_id = session.id if session is not None else None
    _record_order_event(
        db,
        order,
        "payment_confirmed",
        user.id,
        details=f"M-Pesa payment confirmed with receipt {receipt}.",
    )
    queue_order_notification(db, order, "payment_confirmed", f"Payment confirmed for {order.order_number}.")
    log_activity(db, user_id=user.id, action=ActivityAction.SALE_COMPLETED, entity_type="customer_order", entity_id=order.id, description=f"M-Pesa payment confirmed for order {order.order_number}: {order.mpesa_receipt_number}")
    db.commit()
    db.refresh(order)
    return order


@private_router.post("/{order_id}/payment/record", response_model=CustomerOrderRead)
def record_order_cash_payment(
    order_id: int,
    payload: CustomerOrderPaymentRecord,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    order = db.scalar(
        _order_query(order_id)
        .where(CustomerOrder.shop_id == user.shop_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_method == OrderPaymentMethod.MANUAL_MPESA:
        raise HTTPException(
            status_code=409,
            detail="Confirm M-Pesa with its receipt number instead.",
        )
    if order.status in {
        CustomerOrderStatus.REJECTED,
        CustomerOrderStatus.CANCELLED,
    }:
        raise HTTPException(status_code=409, detail="This order is already closed")
    eligible_statuses = (
        {CustomerOrderStatus.READY_FOR_PICKUP, CustomerOrderStatus.DELIVERED}
        if order.payment_method == OrderPaymentMethod.PAY_AT_PICKUP
        else {CustomerOrderStatus.OUT_FOR_DELIVERY, CustomerOrderStatus.DELIVERED}
    )
    if order.status not in eligible_statuses:
        raise HTTPException(
            status_code=409,
            detail="Record cash payment when the order is ready for handoff or delivered.",
        )
    if order.payment_status == OrderPaymentStatus.PAID:
        return order
    session = get_open_session(db, user.shop_id, lock=True)
    if session is None:
        raise HTTPException(status_code=422, detail="Open a cash session before recording payment")

    reference = payload.reference.strip() if payload.reference else None
    order.payment_status = OrderPaymentStatus.PAID
    order.payment_reference = reference
    order.paid_at = datetime.now(timezone.utc)
    order.paid_by_user_id = user.id
    order.session_id = session.id
    _record_order_event(
        db,
        order,
        "payment_confirmed",
        user.id,
        details=(
            f"{order.payment_method.value.replace('_', ' ').title()} payment recorded."
            + (f" Reference: {reference}." if reference else "")
        ),
    )
    queue_order_notification(
        db,
        order,
        "payment_confirmed",
        f"Payment confirmed for order {order.order_number}.",
    )
    db.commit()
    db.refresh(order)
    return order


@private_router.get("/{order_id}/history", response_model=list[CustomerOrderEventRead])
def get_customer_order_history(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    order = db.scalar(
        select(CustomerOrder.id).where(
            CustomerOrder.id == order_id,
            CustomerOrder.shop_id == user.shop_id,
        )
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    events = db.scalars(
        select(CustomerOrderEvent)
        .options(selectinload(CustomerOrderEvent.actor))
        .where(
            CustomerOrderEvent.order_id == order_id,
            CustomerOrderEvent.shop_id == user.shop_id,
        )
        .order_by(CustomerOrderEvent.created_at, CustomerOrderEvent.id)
    ).all()
    return [
        CustomerOrderEventRead(
            id=event.id,
            event_type=event.event_type,
            from_status=event.from_status,
            to_status=event.to_status,
            details=event.details,
            actor_name=event.actor.full_name if event.actor else None,
            created_at=event.created_at,
        )
        for event in events
    ]


def process_order_mpesa_callback(db: Session, payload: dict[str, Any]) -> bool:
    try:
        callback = payload["Body"]["stkCallback"]
        checkout_id = str(callback["CheckoutRequestID"])
        result_code = int(callback["ResultCode"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Malformed Safaricom STK callback.") from exc
    order = db.scalar(_order_query(None).where(CustomerOrder.mpesa_checkout_request_id == checkout_id).with_for_update())
    if order is None:
        return False
    if order.payment_status == OrderPaymentStatus.PAID:
        return True
    if str(callback.get("MerchantRequestID")) != order.mpesa_merchant_request_id:
        return False
    if result_code != 0:
        order.payment_status = OrderPaymentStatus.FAILED
        queue_order_notification(db, order, "payment_failed", f"Payment failed for {order.order_number}. You can try again.")
        _record_order_event(
            db,
            order,
            "payment_failed",
            None,
            details=f"M-Pesa payment failed for {order.order_number}.",
        )
        db.commit()
        return True
    entries = callback.get("CallbackMetadata", {}).get("Item", [])
    metadata = {entry.get("Name"): entry.get("Value") for entry in entries if isinstance(entry, dict)}
    try:
        receipt = str(metadata["MpesaReceiptNumber"]).strip()
        paid_amount = Decimal(str(metadata["Amount"]))
        paid_phone = normalize_phone_number(str(metadata["PhoneNumber"]))
    except (KeyError, ValueError):
        return False
    if paid_amount != order.total or paid_phone != order.mpesa_phone_number or not receipt:
        return False
    order.payment_status = OrderPaymentStatus.PAID
    order.mpesa_receipt_number = receipt
    order.payment_reference = receipt
    order.paid_at = datetime.now(timezone.utc)
    session = get_open_session(db, order.shop_id, lock=True)
    order.session_id = session.id if session is not None else None
    _record_order_event(
        db,
        order,
        "payment_confirmed",
        None,
        details=f"M-Pesa payment confirmed with receipt {receipt}.",
    )
    queue_order_notification(db, order, "payment_confirmed", f"Payment confirmed for {order.order_number}.")
    db.commit()
    return True
