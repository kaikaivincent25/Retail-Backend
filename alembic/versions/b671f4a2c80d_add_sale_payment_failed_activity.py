"""add sale payment failure activity action

Revision ID: b671f4a2c80d
Revises: f2a61b9c401e
Create Date: 2026-10-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b671f4a2c80d"
down_revision: Union[str, Sequence[str], None] = "f2a61b9c401e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE activity_action ADD VALUE IF NOT EXISTS 'sale_payment_failed'")


def downgrade() -> None:
    # PostgreSQL does not support safely removing a value from an enum type.
    pass
