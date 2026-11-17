"""add sales recommendation groups and shop daypart settings

Revision ID: e2f4a6c8d0b1
Revises: f4a1b2c3d4e5
Create Date: 2026-11-17 13:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f4a6c8d0b1"
down_revision: Union[str, Sequence[str], None] = "f4a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("sales_group", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "ck_products_sales_group",
        "products",
        "sales_group IS NULL OR sales_group IN ('breakfast', 'everyday', 'evening')",
    )
    op.add_column(
        "shops",
        sa.Column("breakfast_start_minute", sa.Integer(), server_default="360", nullable=False),
    )
    op.add_column(
        "shops",
        sa.Column("breakfast_end_minute", sa.Integer(), server_default="630", nullable=False),
    )
    op.add_column(
        "shops",
        sa.Column("evening_start_minute", sa.Integer(), server_default="960", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("shops", "evening_start_minute")
    op.drop_column("shops", "breakfast_end_minute")
    op.drop_column("shops", "breakfast_start_minute")
    op.drop_constraint("ck_products_sales_group", "products", type_="check")
    op.drop_column("products", "sales_group")
