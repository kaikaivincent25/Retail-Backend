"""add cash deposits

Revision ID: 9c13d7a2f480
Revises: ebb0b6a07dc7
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c13d7a2f480"
down_revision: Union[str, Sequence[str], None] = "ebb0b6a07dc7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    frequency = sa.Enum("daily", "weekly", name="deposit_frequency")
    op.create_table(
        "cash_deposits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("frequency", frequency, nullable=False),
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
        sa.CheckConstraint("amount > 0", name="ck_cash_deposits_amount_positive"),
        sa.ForeignKeyConstraint(["session_id"], ["cash_sessions.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cash_deposits_shop_id", "cash_deposits", ["shop_id"])
    op.create_index("ix_cash_deposits_session_id", "cash_deposits", ["session_id"])
    op.create_index("ix_cash_deposits_user_id", "cash_deposits", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_cash_deposits_user_id", table_name="cash_deposits")
    op.drop_index("ix_cash_deposits_session_id", table_name="cash_deposits")
    op.drop_index("ix_cash_deposits_shop_id", table_name="cash_deposits")
    op.drop_table("cash_deposits")
    sa.Enum(name="deposit_frequency").drop(op.get_bind(), checkfirst=True)
