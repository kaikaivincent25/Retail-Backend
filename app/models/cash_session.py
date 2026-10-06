import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.user import User


class SessionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class CashSession(TimestampMixin, Base):
    __tablename__ = "cash_sessions"
    __table_args__ = (
        CheckConstraint("opening_cash >= 0", name="ck_cash_sessions_opening_nonneg"),
        Index(
            "uq_cash_sessions_open_shop",
            "shop_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    opening_cash: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    closing_cash: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    expected_cash: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    difference: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status", values_callable=lambda e: [m.value for m in e]),
        default=SessionStatus.OPEN,
        nullable=False,
    )

    user: Mapped[User] = relationship()