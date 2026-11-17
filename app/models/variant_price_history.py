from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class VariantPriceHistory(TimestampMixin, Base):
    __tablename__ = "variant_price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id"), nullable=False, index=True
    )
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    new_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    changed_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
