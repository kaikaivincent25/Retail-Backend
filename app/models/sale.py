import enum
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.shop import Shop
from app.models.user import User


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    MPESA = "mpesa"
    POCHI = "pochi"
    TILL = "till"
    PAYBILL = "paybill"


class SaleStatus(str, enum.Enum):
    COMPLETED = "completed"
    VOIDED = "voided"   # used from Phase 13 onward; not created by any code yet
    PENDING = "pending"
    FAILED = "failed"


class Sale(TimestampMixin, Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount_received: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    change: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="payment_method", values_callable=lambda e: [m.value for m in e]),
        default=PaymentMethod.CASH,
        nullable=False,
    )
    status: Mapped[SaleStatus] = mapped_column(
        Enum(SaleStatus, name="sale_status", values_callable=lambda e: [m.value for m in e]),
        default=SaleStatus.COMPLETED,
        nullable=False,
    )
    mpesa_checkout_request_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    mpesa_merchant_request_id: Mapped[str | None] = mapped_column(String(100))
    mpesa_phone_number: Mapped[str | None] = mapped_column(String(12))
    mpesa_receipt_number: Mapped[str | None] = mapped_column(String(30))
    payment_destination_number: Mapped[str | None] = mapped_column(String(50))
    payment_account_number: Mapped[str | None] = mapped_column(String(100))

    shop: Mapped[Shop] = relationship()
    cashier: Mapped[User] = relationship()
    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", cascade="all, delete-orphan")
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_sessions.id"), nullable=True, index=True
    )


class SaleItem(TimestampMixin, Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False, index=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"), nullable=False)

    # Snapshot at time of sale — never re-derived from the live variant later
    variant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit_cost_at_sale: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    sale: Mapped[Sale] = relationship(back_populates="items")