from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.shop import Shop
from app.models.customer_activity import CustomerActivity


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0",
            name="ck_customers_credit_limit_nonnegative",
        ),
        CheckConstraint(
            "lead_status IN ('new', 'contacted', 'interested', 'won', 'lost')",
            name="ck_customers_lead_status",
        ),
        Index("ix_customers_shop_active_name", "shop_id", "is_active", "full_name"),
        Index("ix_customers_shop_phone_normalized", "shop_id", "phone_normalized"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(
        ForeignKey("shops.id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    phone_normalized: Mapped[str | None] = mapped_column(String(15), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new", server_default="new"
    )
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    identity_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    shop: Mapped[Shop] = relationship()
    activities: Mapped[list["CustomerActivity"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    orders: Mapped[list["CustomerOrder"]] = relationship(back_populates="customer")
