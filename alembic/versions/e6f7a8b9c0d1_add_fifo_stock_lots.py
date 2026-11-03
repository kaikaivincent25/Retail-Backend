"""add FIFO stock lots and allocations

Revision ID: e6f7a8b9c0d1
Revises: d7e9f1a2b304
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d7e9f1a2b304"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_lots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("variant_id", sa.Integer(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("received_quantity", sa.Integer(), nullable=False),
        sa.Column("remaining_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stock_lots_variant_id", "stock_lots", ["variant_id"])

    op.create_table(
        "stock_lot_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lot_id", sa.Integer(), sa.ForeignKey("stock_lots.id"), nullable=False),
        sa.Column("stock_movement_id", sa.Integer(), sa.ForeignKey("stock_movements.id"), nullable=False),
        sa.Column("sale_item_id", sa.Integer(), sa.ForeignKey("sale_items.id"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=False),
    )
    op.create_index("ix_stock_lot_allocations_lot_id", "stock_lot_allocations", ["lot_id"])
    op.create_index("ix_stock_lot_allocations_stock_movement_id", "stock_lot_allocations", ["stock_movement_id"])
    op.create_index("ix_stock_lot_allocations_sale_item_id", "stock_lot_allocations", ["sale_item_id"])

    # Preserve current inventory as an opening FIFO lot. Unknown-cost stock
    # remains blocked from sale by the existing cost-confidence rule.
    op.execute(sa.text("""
        INSERT INTO stock_lots
            (variant_id, received_quantity, remaining_quantity, unit_cost, created_at, updated_at)
        SELECT id, quantity, quantity, cost_price, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM variants
        WHERE quantity > 0 AND cost_price_is_known = TRUE
    """))


def downgrade() -> None:
    op.drop_index("ix_stock_lot_allocations_sale_item_id", table_name="stock_lot_allocations")
    op.drop_index("ix_stock_lot_allocations_stock_movement_id", table_name="stock_lot_allocations")
    op.drop_index("ix_stock_lot_allocations_lot_id", table_name="stock_lot_allocations")
    op.drop_table("stock_lot_allocations")
    op.drop_index("ix_stock_lots_variant_id", table_name="stock_lots")
    op.drop_table("stock_lots")
