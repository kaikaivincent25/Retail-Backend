"""make cash sessions shop-wide

Revision ID: a37c6d9e41b2
Revises: c93d6b62748f
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a37c6d9e41b2"
down_revision: Union[str, Sequence[str], None] = "56a6c1da27ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cash_sessions", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE cash_sessions AS sessions
        SET shop_id = users.shop_id
        FROM users
        WHERE sessions.user_id = users.id
        """
    )
    op.alter_column("cash_sessions", "shop_id", nullable=False)
    op.create_foreign_key(
        "fk_cash_sessions_shop_id_shops",
        "cash_sessions",
        "shops",
        ["shop_id"],
        ["id"],
    )
    op.create_index(
        "ix_cash_sessions_shop_id", "cash_sessions", ["shop_id"], unique=False
    )

    # Preserve the latest active session; older overlaps are closed without inventing counts.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (PARTITION BY shop_id ORDER BY id DESC) AS position
            FROM cash_sessions
            WHERE status = 'open'
        )
        UPDATE cash_sessions
        SET status = 'closed',
            closed_at = now(),
            updated_at = now()
        WHERE id IN (SELECT id FROM ranked WHERE position > 1)
        """
    )
    op.create_index(
        "uq_cash_sessions_open_shop",
        "cash_sessions",
        ["shop_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_cash_sessions_open_shop", table_name="cash_sessions")
    op.drop_index("ix_cash_sessions_shop_id", table_name="cash_sessions")
    op.drop_constraint(
        "fk_cash_sessions_shop_id_shops", "cash_sessions", type_="foreignkey"
    )
    op.drop_column("cash_sessions", "shop_id")
