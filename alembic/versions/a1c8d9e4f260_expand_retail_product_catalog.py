"""expand product details and retail unit options

Revision ID: a1c8d9e4f260
Revises: f7b236a8c940
Create Date: 2026-10-23 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c8d9e4f260"
down_revision: Union[str, Sequence[str], None] = "f7b236a8c940"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("brand", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "products",
        sa.Column("attributes", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.create_index("ix_products_brand", "products", ["brand"], unique=False)
    op.add_column("variants", sa.Column("barcode", sa.String(length=64), nullable=True))
    op.create_index("ix_variants_barcode", "variants", ["barcode"], unique=False)

    for unit in (
        "each", "pack", "pair", "set", "box", "case", "dozen", "bottle",
        "can", "sheet", "roll", "metre", "centimetre",
    ):
        op.execute(f"ALTER TYPE unit ADD VALUE IF NOT EXISTS '{unit}'")


def downgrade() -> None:
    op.drop_index("ix_variants_barcode", table_name="variants")
    op.drop_column("variants", "barcode")
    op.drop_index("ix_products_brand", table_name="products")
    op.drop_column("products", "attributes")
    op.drop_column("products", "description")
    op.drop_column("products", "brand")
