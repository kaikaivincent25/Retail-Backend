"""add manual M-Pesa payment destinations and sale methods

Revision ID: f2a61b9c401e
Revises: de4a91f37b2c
Create Date: 2026-10-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a61b9c401e"
down_revision: Union[str, Sequence[str], None] = "c0af3d5027a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'pochi'")
    op.execute("ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'till'")
    op.execute("ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'paybill'")
    op.add_column("shops", sa.Column("mpesa_pochi_number", sa.String(length=50), nullable=True))
    op.add_column("shops", sa.Column("mpesa_till_number", sa.String(length=50), nullable=True))
    op.add_column("shops", sa.Column("mpesa_paybill_number", sa.String(length=50), nullable=True))
    op.add_column(
        "shops",
        sa.Column("mpesa_paybill_account_number", sa.String(length=100), nullable=True),
    )
    op.add_column("sales", sa.Column("payment_destination_number", sa.String(length=50), nullable=True))
    op.add_column("sales", sa.Column("payment_account_number", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("sales", "payment_account_number")
    op.drop_column("sales", "payment_destination_number")
    op.drop_column("shops", "mpesa_paybill_account_number")
    op.drop_column("shops", "mpesa_paybill_number")
    op.drop_column("shops", "mpesa_till_number")
    op.drop_column("shops", "mpesa_pochi_number")
