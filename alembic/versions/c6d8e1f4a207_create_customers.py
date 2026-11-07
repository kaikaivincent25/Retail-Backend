"""create customers

Revision ID: c6d8e1f4a207
Revises: 84a3798b914e
Create Date: 2026-11-07 14:52:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6d8e1f4a207"
down_revision: Union[str, Sequence[str], None] = ("84a3798b914e", "e6f7a8b9c0d1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("credit_limit", sa.Numeric(10, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("credit_limit IS NULL OR credit_limit >= 0", name="ck_customers_credit_limit_nonnegative"),
    )
    op.create_index("ix_customers_shop_id", "customers", ["shop_id"])
    op.create_index(
        "ix_customers_shop_active_name",
        "customers",
        ["shop_id", "is_active", "full_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_customers_shop_active_name", table_name="customers")
    op.drop_index("ix_customers_shop_id", table_name="customers")
    op.drop_table("customers")
