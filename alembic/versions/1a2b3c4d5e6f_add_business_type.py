"""add business type to shops

Revision ID: 1a2b3c4d5e6f
Revises: f7b236a8c940
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = ("f7b236a8c940", "b2c3d4e5f6a7")
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column(
        "shops",
        sa.Column("business_type", sa.String(length=40), server_default="general_retail", nullable=False),
    )

def downgrade() -> None:
    op.drop_column("shops", "business_type")
