import enum

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.user import User


class ActivityAction(str, enum.Enum):
    LOGIN = "login"
    SALE_COMPLETED = "sale_completed"
    SALE_VOIDED = "sale_voided"                # not triggerable yet — no void endpoint exists
    CART_CLEARED = "cart_cleared"               # frontend-only event, wired in Phase 22/23
    INVENTORY_ADJUSTED = "inventory_adjusted"
    PRODUCT_CREATED = "product_created"
    VARIANT_CREATED = "variant_created"
    CASH_SESSION_OPENED = "cash_session_opened"
    CASH_SESSION_CLOSED = "cash_session_closed"
    EXPENSE_LOGGED = "expense_logged"


HIGH_RISK_ACTIONS = {
    ActivityAction.SALE_VOIDED,
    ActivityAction.CART_CLEARED,
    ActivityAction.INVENTORY_ADJUSTED,
}


class ActivityLog(TimestampMixin, Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    action: Mapped[ActivityAction] = mapped_column(
        Enum(ActivityAction, name="activity_action", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_high_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped[User] = relationship()