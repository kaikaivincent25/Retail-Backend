from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.variant import Variant


class BulkPreset(TimestampMixin, Base):
    __tablename__ = "bulk_presets"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"), nullable=False, index=True)

    label: Mapped[str] = mapped_column(String(50), nullable=False)   # e.g. "1/4 kg", "500ml"
    amount: Mapped[int] = mapped_column(nullable=False)                # base units, e.g. 250
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    variant: Mapped[Variant] = relationship()