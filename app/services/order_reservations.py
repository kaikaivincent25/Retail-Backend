from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer_order import CustomerOrder
from app.models.order_reservation import OrderReservation, ReservationStatus
from app.models.variant import Variant


RESERVATION_HOURS = 24


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def active_reserved_quantity(db: Session, variant_id: int) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(OrderReservation.quantity), 0)).where(
            OrderReservation.variant_id == variant_id,
            OrderReservation.status == ReservationStatus.ACTIVE,
            (OrderReservation.expires_at.is_(None) | (OrderReservation.expires_at > utc_now())),
        )
    )
    return int(total or 0)


def reserve_order(db: Session, order: CustomerOrder, user_id: int) -> None:
    existing = db.scalar(select(OrderReservation.id).where(OrderReservation.order_id == order.id, OrderReservation.status == ReservationStatus.ACTIVE))
    if existing is not None:
        return

    variant_ids = [item.variant_id for item in order.items]
    variants = db.scalars(select(Variant).where(Variant.id.in_(variant_ids)).order_by(Variant.id).with_for_update()).all()
    variants_by_id = {variant.id: variant for variant in variants}
    expiry = utc_now() + timedelta(hours=RESERVATION_HOURS)
    for item in order.items:
        variant = variants_by_id.get(item.variant_id)
        if variant is None:
            raise ValueError(f"Variant {item.variant_id} no longer exists")
        reserved = active_reserved_quantity(db, variant.id)
        if variant.quantity - reserved < item.quantity:
            raise ValueError(f"Insufficient available stock for '{variant.name}'")
        db.add(OrderReservation(order_id=order.id, variant_id=variant.id, quantity=item.quantity, expires_at=expiry))


def release_order_reservations(db: Session, order_id: int, user_id: int | None = None) -> int:
    reservations = db.scalars(select(OrderReservation).where(OrderReservation.order_id == order_id, OrderReservation.status == ReservationStatus.ACTIVE).with_for_update()).all()
    now = utc_now()
    for reservation in reservations:
        reservation.status = ReservationStatus.RELEASED
        reservation.released_at = now
        reservation.released_by_user_id = user_id
    return len(reservations)


def consume_order_reservations(db: Session, order_id: int) -> None:
    reservations = db.scalars(select(OrderReservation).where(OrderReservation.order_id == order_id, OrderReservation.status == ReservationStatus.ACTIVE).with_for_update()).all()
    for reservation in reservations:
        reservation.status = ReservationStatus.CONSUMED


def expire_reservations(db: Session) -> int:
    reservations = db.scalars(
        select(OrderReservation).where(
            OrderReservation.status == ReservationStatus.ACTIVE,
            OrderReservation.expires_at.is_not(None),
            OrderReservation.expires_at <= utc_now(),
        ).with_for_update()
    ).all()
    for reservation in reservations:
        reservation.status = ReservationStatus.RELEASED
        reservation.released_at = utc_now()
    return len(reservations)
