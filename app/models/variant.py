import enum
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.product import Product


class Unit(str, enum.Enum):
    PIECE = "piece"
    PACKET = "packet"
    GRAM = "gram"
    KG = "kg"
    ML = "ml"
    LITRE = "litre"


class SaleMode(str, enum.Enum):
    FIXED = "fixed"   # sold in whole units at a fixed price each (e.g. Kabras 2kg packet)
    BULK = "bulk"      # sold by measured amount at a price per base unit (e.g. loose sugar)


class Variant(TimestampMixin, Base):
    __tablename__ = "variants"
    __table_args__ = (
        UniqueConstraint("product_id", "name", name="uq_variants_product_name"),
        CheckConstraint("selling_price >= 0", name="ck_variants_selling_price_nonneg"),
        CheckConstraint("cost_price >= 0", name="ck_variants_cost_price_nonneg"),
        CheckConstraint("quantity >= 0", name="ck_variants_quantity_nonneg"),
        CheckConstraint("reorder_level >= 0", name="ck_variants_reorder_level_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, index=True
    )

    # e.g. "Kabras 2kg", "Mumias 1kg", "Loose"
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    unit: Mapped[Unit] = mapped_column(
        __import__("sqlalchemy").Enum(Unit, name="unit", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    sale_mode: Mapped[SaleMode] = mapped_column(
        __import__("sqlalchemy").Enum(SaleMode, name="sale_mode", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=SaleMode.FIXED,
    )

    # FIXED: size of one pack in base units, purely informational (e.g. 2000 for "2kg" in grams).
    # BULK: always 1 — a bulk variant has no fixed size, price is per base unit.
    unit_quantity: Mapped[int] = mapped_column(nullable=False, default=1)

    # FIXED: price per whole unit/packet.
    # BULK: price per single base unit (e.g. price per gram, or per ml).
    selling_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))

    sku: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true", nullable=False)

    product: Mapped[Product] = relationship()

    quantity: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    reorder_level: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")