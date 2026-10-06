"""add database integrity constraints

Revision ID: c93d6b62748f
Revises: 75e689959560
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c93d6b62748f"
down_revision: Union[str, Sequence[str], None] = "75e689959560"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(
        "ck_expenses_amount_positive",
        "expenses",
        "amount > 0",
    )
    op.create_check_constraint(
        "ck_cash_sessions_opening_nonneg",
        "cash_sessions",
        "opening_cash >= 0",
    )
    op.create_check_constraint(
        "ck_variants_quantity_nonneg",
        "variants",
        "quantity >= 0",
    )
    op.create_check_constraint(
        "ck_variants_reorder_level_nonneg",
        "variants",
        "reorder_level >= 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_expenses_amount_positive", "expenses", type_="check")
    op.drop_constraint("ck_cash_sessions_opening_nonneg", "cash_sessions", type_="check")
    op.drop_constraint("ck_variants_quantity_nonneg", "variants", type_="check")
    op.drop_constraint("ck_variants_reorder_level_nonneg", "variants", type_="check")
