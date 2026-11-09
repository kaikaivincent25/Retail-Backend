"""add cash session review breakdown

Revision ID: c8d9e0f1a2b3
Revises: b4c5d6e7f8a9
Create Date: 2026-11-09 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cash_sessions",
        sa.Column("cash_sales_total", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "cash_sessions",
        sa.Column("cash_collections_total", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "cash_sessions",
        sa.Column("cash_expenses_total", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "cash_sessions",
        sa.Column("credit_sales_total", sa.Numeric(10, 2), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE cash_sessions
            SET cash_sales_total = COALESCE((
                    SELECT SUM(sales.total)
                    FROM sales
                    WHERE sales.session_id = cash_sessions.id
                      AND sales.payment_method = 'cash'
                      AND sales.is_credit = FALSE
                      AND sales.status = 'completed'
                ), 0),
                cash_collections_total = COALESCE((
                    SELECT SUM(customer_payments.amount)
                    FROM customer_payments
                    WHERE customer_payments.session_id = cash_sessions.id
                      AND customer_payments.payment_method = 'cash'
                ), 0),
                cash_expenses_total = COALESCE((
                    SELECT SUM(expenses.amount)
                    FROM expenses
                    WHERE expenses.session_id = cash_sessions.id
                      AND expenses.funding_source = 'cash'
                ), 0),
                credit_sales_total = COALESCE((
                    SELECT SUM(sales.total)
                    FROM sales
                    WHERE sales.session_id = cash_sessions.id
                      AND sales.is_credit = TRUE
                      AND sales.status = 'completed'
                ), 0)
            WHERE cash_sessions.status = 'closed'
            """
        )
    )


def downgrade() -> None:
    op.drop_column("cash_sessions", "credit_sales_total")
    op.drop_column("cash_sessions", "cash_expenses_total")
    op.drop_column("cash_sessions", "cash_collections_total")
    op.drop_column("cash_sessions", "cash_sales_total")
