import enum
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.variant import Variant


class MovementType(str, enum.Enum):
    PURCHASE = "purchase"      # stock received (e.g. the 50kg sack arriving)
    SALE = "sale"               # stock leaving via a sale (Phase 9/10 will create these)
    ADJUSTMENT = "adjustment"   # manual correction (stocktake mismatch, etc.)
    DAMAGE = "damage"           # stock written off (breakage, spoilage, theft)
    STAFF_CONSUMPTION = "staff_consumption"


class StockMovement(TimestampMixin, Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id"), nullable=False, index=True
    )
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, name="movement_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(nullable=False)  # signed: +50000, -250, etc.
    previous_quantity: Mapped[int] = mapped_column(nullable=False)
    new_quantity: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    unit_cost_at_time: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    variant: Mapped[Variant] = relationship()