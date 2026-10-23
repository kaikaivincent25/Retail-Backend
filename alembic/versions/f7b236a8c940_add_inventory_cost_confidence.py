"""track known inventory cost and cost purchases

Revision ID: f7b236a8c940
Revises: bce8b3542098
Create Date: 2026-10-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7b236a8c940"
down_revision: Union[str, Sequence[str], None] = "bce8b3542098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "variants",
        sa.Column("cost_price_is_known", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "sale_items",
        sa.Column("cost_is_known_at_sale", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Existing zero-cost records cannot be distinguished from unentered costs.
    op.execute("UPDATE variants SET cost_price_is_known = cost_price > 0")
    op.execute("UPDATE sale_items SET cost_is_known_at_sale = unit_cost_at_sale > 0")
    op.create_check_constraint(
        "ck_stock_movements_unit_cost_nonneg",
        "stock_movements",
        "unit_cost_at_time IS NULL OR unit_cost_at_time >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_stock_movements_unit_cost_nonneg", "stock_movements", type_="check")
    op.drop_column("sale_items", "cost_is_known_at_sale")
    op.drop_column("variants", "cost_price_is_known")
