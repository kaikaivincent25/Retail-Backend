import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class CustomerOrderStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PREPARING = "preparing"
    READY_FOR_PICKUP = "ready_for_pickup"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OrderFulfilment(str, enum.Enum):
    DELIVERY = "delivery"
    PICKUP = "pickup"


class OrderPaymentMethod(str, enum.Enum):
    PAY_ON_DELIVERY = "pay_on_delivery"
    PAY_AT_PICKUP = "pay_at_pickup"
    MANUAL_MPESA = "manual_mpesa"


class OrderPaymentStatus(str, enum.Enum):
    PENDING = "pending"
    INITIATED = "initiated"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class CustomerOrder(TimestampMixin, Base):
    __tablename__ = "customer_orders"
    __table_args__ = (
        UniqueConstraint("shop_id", "order_number", name="uq_customer_orders_shop_number"),
        UniqueConstraint("public_token", name="uq_customer_orders_public_token"),
        UniqueConstraint("tracking_code", name="uq_customer_orders_tracking_code"),
        Index("ix_customer_orders_shop_phone_normalized", "shop_id", "customer_phone_normalized"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    order_number: Mapped[str] = mapped_column(String(24), nullable=False)
    public_token: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tracking_code: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[CustomerOrderStatus] = mapped_column(
        Enum(CustomerOrderStatus, name="customer_order_status", values_callable=lambda e: [m.value for m in e]),
        default=CustomerOrderStatus.PENDING,
        nullable=False,
        index=True,
    )
    fulfilment: Mapped[OrderFulfilment] = mapped_column(
        Enum(OrderFulfilment, name="order_fulfilment", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    payment_method: Mapped[OrderPaymentMethod] = mapped_column(
        Enum(OrderPaymentMethod, name="order_payment_method", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    payment_status: Mapped[OrderPaymentStatus] = mapped_column(
        Enum(OrderPaymentStatus, name="order_payment_status", values_callable=lambda e: [m.value for m in e]),
        default=OrderPaymentStatus.PENDING,
        nullable=False,
        index=True,
    )
    mpesa_checkout_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    mpesa_merchant_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mpesa_phone_number: Mapped[str | None] = mapped_column(String(12), nullable=True)
    mpesa_receipt_number: Mapped[str | None] = mapped_column(String(30), nullable=True, unique=True)
    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    customer_phone_normalized: Mapped[str | None] = mapped_column(String(15), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    estate: Mapped[str | None] = mapped_column(String(150), nullable=True)
    landmark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_delivery_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shop_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_by_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_sessions.id"), nullable=True, index=True
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id"), nullable=True, unique=True)
    customer_notified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    customer_reminder_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    items: Mapped[list["CustomerOrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    customer: Mapped["Customer | None"] = relationship(back_populates="orders")
    events: Mapped[list["CustomerOrderEvent"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class CustomerOrderEvent(TimestampMixin, Base):
    __tablename__ = "customer_order_events"
    __table_args__ = (
        Index("ix_customer_order_events_order_created", "order_id", "created_at"),
        Index("ix_customer_order_events_shop_created", "shop_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    order: Mapped[CustomerOrder] = relationship(back_populates="events")
    actor: Mapped["User | None"] = relationship()


class CustomerOrderItem(TimestampMixin, Base):
    __tablename__ = "customer_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("customer_orders.id"), nullable=False, index=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"), nullable=False)
    variant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    order: Mapped[CustomerOrder] = relationship(back_populates="items")
