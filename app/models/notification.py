import enum

from sqlalchemy import Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class NotificationChannel(str, enum.Enum):
    WHATSAPP = "whatsapp"
    SMS = "sms"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class NotificationEvent(TimestampMixin, Base):
    __tablename__ = "notification_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("customer_orders.id"), nullable=True, index=True)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    recipient: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status", values_callable=lambda e: [m.value for m in e]),
        default=NotificationStatus.PENDING,
        nullable=False,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    provider_message_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
