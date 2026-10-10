"""snapshot unit cost on sale items

Revision ID: c4e8b3109d2a
Revises: b671f4a2c80d
Create Date: 2026-10-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8b3109d2a"
down_revision: Union[str, Sequence[str], None] = "b671f4a2c80d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sale_items",
        sa.Column("unit_cost_at_sale", sa.Numeric(10, 2), nullable=True),
    )
    op.execute(
        """
        UPDATE sale_items
        SET unit_cost_at_sale = variants.cost_price
        FROM variants
        WHERE variants.id = sale_items.variant_id
        """
    )
    op.alter_column("sale_items", "unit_cost_at_sale", nullable=False)


def downgrade() -> None:
    op.drop_column("sale_items", "unit_cost_at_sale")
