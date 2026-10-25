"""add expense funding source

Revision ID: b2c3d4e5f6a7
Revises: a1c8d9e4f260
Create Date: 2026-10-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1c8d9e4f260"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "expenses",
        sa.Column(
            "funding_source",
            sa.String(length=10),
            nullable=False,
            server_default="cash",
        ),
    )


def downgrade() -> None:
    op.drop_column("expenses", "funding_source")
