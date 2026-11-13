import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class ReservationStatus(str, enum.Enum):
    ACTIVE = "active"
    RELEASED = "released"
    CONSUMED = "consumed"


class OrderReservation(TimestampMixin, Base):
    __tablename__ = "order_reservations"
    __table_args__ = (UniqueConstraint("order_id", "variant_id", name="uq_order_reservations_order_variant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("customer_orders.id"), nullable=False, index=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, name="reservation_status", values_callable=lambda e: [m.value for m in e]),
        default=ReservationStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    order = relationship("CustomerOrder")
    variant = relationship("Variant")
