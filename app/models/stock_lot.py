from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class StockLot(TimestampMixin, Base):
    """A received batch of stock consumed in FIFO order."""

    __tablename__ = "stock_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"), nullable=False, index=True)
    received_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    variant = relationship("Variant")
    allocations = relationship("StockLotAllocation", back_populates="lot")


class StockLotAllocation(Base):
    """Records which FIFO lots supplied an outgoing stock movement."""

    __tablename__ = "stock_lot_allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("stock_lots.id"), nullable=False, index=True)
    stock_movement_id: Mapped[int] = mapped_column(
        ForeignKey("stock_movements.id"), nullable=False, index=True
    )
    sale_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("sale_items.id"), nullable=True, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    lot = relationship("StockLot", back_populates="allocations")
