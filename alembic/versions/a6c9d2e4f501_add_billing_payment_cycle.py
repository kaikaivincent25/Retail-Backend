"""add billing payment cycle

Revision ID: a6c9d2e4f501
Revises: e1f3a5b7c9d1
"""

from alembic import op
import sqlalchemy as sa


revision = "a6c9d2e4f501"
down_revision = "e1f3a5b7c9d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "billing_payments",
        sa.Column(
            "billing_cycle",
            sa.String(length=10),
            nullable=False,
            server_default="monthly",
        ),
    )


def downgrade() -> None:
    op.drop_column("billing_payments", "billing_cycle")
