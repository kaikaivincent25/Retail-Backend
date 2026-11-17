"""add variant price history

Revision ID: f6a8c0d2e4b7
Revises: e2f4a6c8d0b1
Create Date: 2026-11-17 16:55:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a8c0d2e4b7"
down_revision: Union[str, Sequence[str], None] = "e2f4a6c8d0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "variant_price_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=False),
        sa.Column("old_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("new_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"], ["users.id"], name="fk_variant_price_history_user"
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["variants.id"], name="fk_variant_price_history_variant"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_variant_price_history_variant_id",
        "variant_price_history",
        ["variant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_variant_price_history_variant_id",
        table_name="variant_price_history",
    )
    op.drop_table("variant_price_history")
