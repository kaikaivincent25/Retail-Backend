import secrets
import re
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_cashier
from app.core.database import get_db
from app.models.customer_order import (
    CustomerOrder,
    CustomerOrderItem,
    CustomerOrderStatus,
    OrderFulfilment,
    OrderPaymentMethod,
    OrderPaymentStatus,
)
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
from app.schemas.customer_order import (
    CustomerOrderCreate,
    CustomerOrderRead,
    CustomerOrderStatusUpdate,
    PublicOrderRead,
)

public_router = APIRouter(prefix="/public", tags=["Customer orders"])
private_router = APIRouter(prefix="/orders", tags=["Customer orders"])


def _get_public_shop(db: Session, slug: str) -> Shop:
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_suspended.is_(False)))
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


def _order_query(order_id: int | None = None):
    query = select(CustomerOrder).options(selectinload(CustomerOrder.items))
    if order_id is not None:
        query = query.where(CustomerOrder.id == order_id)
    return query


def _public_order(order: CustomerOrder) -> PublicOrderRead:
    return PublicOrderRead(
        public_token=order.public_token,
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


def _order_number(shop: Shop, order_id: int) -> str:
    prefix = re.sub(r"[^A-Z0-9]", "", (shop.slug or shop.name).upper())[:2] or "SH"
    return f"{prefix}-{1000 + order_id}"


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

    order = CustomerOrder(
        shop_id=shop.id,
        public_token=secrets.token_urlsafe(32),
        fulfilment=payload.fulfilment,
        payment_method=payload.payment_method,
        customer_name=payload.customer_name.strip(),
        customer_phone=payload.customer_phone.strip(),
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


@public_router.get("/orders/{public_token}", response_model=PublicOrderRead)
def track_customer_order(public_token: str, db: Session = Depends(get_db)):
    order = db.scalar(_order_query(None).where(CustomerOrder.public_token == public_token))
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return _public_order(order)


@private_router.get("", response_model=list[CustomerOrderRead])
def list_customer_orders(
    order_status: CustomerOrderStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    expire_reservations(db)
    db.commit()
    query = _order_query(None).where(CustomerOrder.shop_id == user.shop_id)
    if order_status is not None:
        query = query.where(CustomerOrder.status == order_status)
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
        CustomerOrderStatus.READY_FOR_PICKUP: {CustomerOrderStatus.COMPLETED, CustomerOrderStatus.CANCELLED},
        CustomerOrderStatus.OUT_FOR_DELIVERY: {CustomerOrderStatus.DELIVERED, CustomerOrderStatus.COMPLETED},
        CustomerOrderStatus.DELIVERED: {CustomerOrderStatus.COMPLETED},
    }
    if payload.status not in allowed_transitions.get(order.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot move an order from {order.status.value} to {payload.status.value}")
    if payload.status == CustomerOrderStatus.OUT_FOR_DELIVERY and order.fulfilment != OrderFulfilment.DELIVERY:
        raise HTTPException(status_code=409, detail="Pickup orders cannot be sent for delivery")
    if payload.status == CustomerOrderStatus.ACCEPTED:
        try:
            reserve_order(db, order, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if payload.status in {CustomerOrderStatus.REJECTED, CustomerOrderStatus.CANCELLED}:
        release_order_reservations(db, order.id, user.id)
    if payload.status == CustomerOrderStatus.COMPLETED:
        if order.payment_method == OrderPaymentMethod.MANUAL_MPESA and order.payment_status != OrderPaymentStatus.PAID:
            raise HTTPException(status_code=409, detail="Confirm M-Pesa payment before completing this order")
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
                    payment_method=(PaymentMethod.MPESA if order.payment_method == OrderPaymentMethod.MANUAL_MPESA else PaymentMethod.CASH),
                    session_id=session.id,
                    allow_confirmed_mpesa=order.payment_method == OrderPaymentMethod.MANUAL_MPESA,
                )
            except SaleError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            order.sale_id = sale.id
            consume_order_reservations(db, order.id)
    order.status = payload.status
    queue_order_notification(
        db,
        order,
        f"order_{payload.status.value}",
        f"{order.order_number} is now {payload.status.value.replace('_', ' ')}.",
    )
    if "shop_note" in payload.model_fields_set:
        order.shop_note = payload.shop_note
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
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    order.payment_status = OrderPaymentStatus.INITIATED
    order.mpesa_phone_number = phone
    order.mpesa_checkout_request_id = identifiers["checkout_request_id"]
    order.mpesa_merchant_request_id = identifiers["merchant_request_id"]
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
    if order.payment_status == OrderPaymentStatus.PAID and order.mpesa_receipt_number == receipt_number.strip():
        return order
    order.payment_status = OrderPaymentStatus.PAID
    order.mpesa_receipt_number = receipt_number.strip()
    queue_order_notification(db, order, "payment_confirmed", f"Payment confirmed for {order.order_number}.")
    log_activity(db, user_id=user.id, action=ActivityAction.SALE_COMPLETED, entity_type="customer_order", entity_id=order.id, description=f"M-Pesa payment confirmed for order {order.order_number}: {order.mpesa_receipt_number}")
    db.commit()
    db.refresh(order)
    return order


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
    queue_order_notification(db, order, "payment_confirmed", f"Payment confirmed for {order.order_number}.")
    db.commit()
    return True
