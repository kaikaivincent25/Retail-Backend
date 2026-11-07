from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.sale import PaymentMethod

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.sale import Sale
    from app.models.shop import Shop
    from app.models.user import User


class CustomerPayment(TimestampMixin, Base):
    __tablename__ = "customer_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_customer_payments_amount_positive"),
        Index("ix_customer_payments_shop_customer", "shop_id", "customer_id"),
        Index("ix_customer_payments_sale", "sale_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False, index=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_sessions.id"), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="payment_method", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recorded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    shop: Mapped["Shop"] = relationship()
    customer: Mapped["Customer"] = relationship()
    sale: Mapped["Sale"] = relationship(back_populates="payments")
    recorded_by: Mapped["User"] = relationship()
