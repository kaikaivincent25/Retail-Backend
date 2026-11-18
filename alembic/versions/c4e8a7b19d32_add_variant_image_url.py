"""add variant image url

Revision ID: c4e8a7b19d32
Revises: 84a3798b914e, f6a8c0d2e4b7
Create Date: 2026-11-18 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8a7b19d32"
down_revision: Union[str, Sequence[str], None] = ("84a3798b914e", "f6a8c0d2e4b7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("variants", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("variants", "image_url")
