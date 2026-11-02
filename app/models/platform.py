from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class PlatformUser(TimestampMixin, Base):
    __tablename__ = "platform_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")


class PlatformAuditLog(TimestampMixin, Base):
    __tablename__ = "platform_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id"), nullable=False, index=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
