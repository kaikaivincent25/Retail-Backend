"""mark automatically closed cash sessions

Revision ID: c4d2e8a1f907
Revises: 84a3798b914e, b7a8c9d0e1f2
Create Date: 2026-11-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d2e8a1f907"
down_revision: Union[str, Sequence[str], None] = (
    "84a3798b914e",
    "b7a8c9d0e1f2",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cash_sessions",
        sa.Column("auto_closed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("cash_sessions", "auto_closed")
