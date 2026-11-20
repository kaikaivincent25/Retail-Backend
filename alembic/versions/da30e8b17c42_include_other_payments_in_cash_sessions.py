"""include non-cash and online order payments in cash sessions

Revision ID: da30e8b17c42
Revises: c4d2e8a1f907
Create Date: 2026-11-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "da30e8b17c42"
down_revision: Union[str, Sequence[str], None] = "c4d2e8a1f907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cash_sessions", sa.Column("non_cash_sales_total", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column(
        "cash_sessions", sa.Column("sales_total", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column(
        "customer_orders", sa.Column("session_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_customer_orders_session_id_cash_sessions",
        "customer_orders",
        "cash_sessions",
        ["session_id"],
        ["id"],
    )
    op.create_index(
        "ix_customer_orders_session_id", "customer_orders", ["session_id"], unique=False
    )
    op.execute(
        """
        UPDATE customer_orders
        SET session_id = (
            SELECT sales.session_id
            FROM sales
            WHERE sales.id = customer_orders.sale_id
        )
        WHERE sale_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE cash_sessions
        SET non_cash_sales_total = COALESCE((
                SELECT SUM(sales.total)
                FROM sales
                WHERE sales.session_id = cash_sessions.id
                  AND sales.payment_method IN ('mpesa', 'pochi', 'till', 'paybill')
                  AND sales.is_credit = FALSE
                  AND sales.status = 'completed'
            ), 0),
            sales_total = COALESCE((
                SELECT SUM(sales.total)
                FROM sales
                WHERE sales.session_id = cash_sessions.id
                  AND sales.is_credit = FALSE
                  AND sales.status = 'completed'
            ), 0)
        WHERE cash_sessions.status = 'closed'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_customer_orders_session_id", table_name="customer_orders")
    op.drop_constraint(
        "fk_customer_orders_session_id_cash_sessions",
        "customer_orders",
        type_="foreignkey",
    )
    op.drop_column("customer_orders", "session_id")
    op.drop_column("cash_sessions", "sales_total")
    op.drop_column("cash_sessions", "non_cash_sales_total")
