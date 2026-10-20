"""add product image URL

Revision ID: 4f9c8a2d1e6b
Revises: ebb0b6a07dc7
Create Date: 2026-10-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f9c8a2d1e6b"
down_revision: Union[str, Sequence[str], None] = "ebb0b6a07dc7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "image_url")
