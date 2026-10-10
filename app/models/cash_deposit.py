import enum
from decimal import Decimal

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.cash_session import CashSession
from app.models.mixins import TimestampMixin
from app.models.shop import Shop
from app.models.user import User


class DepositFrequency(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class CashDeposit(TimestampMixin, Base):
    __tablename__ = "cash_deposits"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_cash_deposits_amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("cash_sessions.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    frequency: Mapped[DepositFrequency] = mapped_column(
        Enum(
            DepositFrequency,
            name="deposit_frequency",
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )

    shop: Mapped[Shop] = relationship()
    session: Mapped[CashSession] = relationship()
    user: Mapped[User] = relationship()
