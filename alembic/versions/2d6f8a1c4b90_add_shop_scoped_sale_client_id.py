"""add shop-scoped sale client id

Revision ID: 2d6f8a1c4b90
Revises: 9c13d7a2f480
Create Date: 2026-10-14 12:17:33.790000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2d6f8a1c4b90"
down_revision: Union[str, Sequence[str], None] = "9c13d7a2f480"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sales",
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_sales_shop_client_id",
        "sales",
        ["shop_id", "client_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_sales_shop_client_id", "sales", type_="unique")
    op.drop_column("sales", "client_id")
