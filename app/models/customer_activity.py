from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.user import User


class CustomerActivity(TimestampMixin, Base):
    __tablename__ = "customer_activities"
    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('note', 'follow_up', 'lead_status')",
            name="ck_customer_activities_type",
        ),
        CheckConstraint(
            "status IN ('open', 'completed')",
            name="ck_customer_activities_status",
        ),
        Index(
            "ix_customer_activities_customer_created",
            "customer_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="completed", server_default="completed"
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    customer: Mapped["Customer"] = relationship(back_populates="activities")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_user_id])
