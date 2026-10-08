from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Shop(TimestampMixin, Base):
    __tablename__ = "shops"
    __table_args__ = (UniqueConstraint("name", name="uq_shops_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), default="KES", server_default="KES", nullable=False
    )
    mpesa_pochi_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mpesa_till_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mpesa_paybill_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mpesa_paybill_account_number: Mapped[str | None] = mapped_column(String(100), nullable=True)