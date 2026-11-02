"""add service suspension flag to subscriptions

Revision ID: b31d7e4f6a90
Revises: a14c5e8f9b22
Create Date: 2026-11-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b31d7e4f6a90"
down_revision: Union[str, Sequence[str], None] = "a14c5e8f9b22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("service_suspended", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "service_suspended")
