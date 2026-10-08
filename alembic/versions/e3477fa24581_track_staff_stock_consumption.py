"""track staff stock consumption separately from cash expenses

Revision ID: e3477fa24581
Revises: f2a61b9c401e
Create Date: 2026-10-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3477fa24581"
down_revision: Union[str, Sequence[str], None] = "f2a61b9c401e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE movement_type ADD VALUE IF NOT EXISTS 'staff_consumption'")
    op.execute(
        "ALTER TYPE activity_action ADD VALUE IF NOT EXISTS 'staff_consumption_recorded'"
    )
    op.add_column(
        "stock_movements",
        sa.Column("unit_cost_at_time", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_movements", "unit_cost_at_time")
