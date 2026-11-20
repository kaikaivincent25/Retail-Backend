"""add customer order reminder requests

Revision ID: e9c2a7f4b601
Revises: f5d8a1c3e6b2
"""

from alembic import op
import sqlalchemy as sa


revision = "e9c2a7f4b601"
down_revision = "f5d8a1c3e6b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_orders",
        sa.Column("customer_reminder_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_orders", "customer_reminder_requested_at")
