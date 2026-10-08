"""add M-Pesa STK payment support

Revision ID: de4a91f37b2c
Revises: c93d6b62748f
Create Date: 2026-10-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "de4a91f37b2c"
down_revision: Union[str, Sequence[str], None] = "c93d6b62748f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'mpesa'")
    op.execute("ALTER TYPE sale_status ADD VALUE IF NOT EXISTS 'pending'")
    op.execute("ALTER TYPE sale_status ADD VALUE IF NOT EXISTS 'failed'")
    op.add_column("sales", sa.Column("mpesa_checkout_request_id", sa.String(length=100)))
    op.add_column("sales", sa.Column("mpesa_merchant_request_id", sa.String(length=100)))
    op.add_column("sales", sa.Column("mpesa_phone_number", sa.String(length=12)))
    op.add_column("sales", sa.Column("mpesa_receipt_number", sa.String(length=30)))
    op.create_unique_constraint(
        "uq_sales_mpesa_checkout_request_id",
        "sales",
        ["mpesa_checkout_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_sales_mpesa_checkout_request_id", "sales", type_="unique")
    op.drop_column("sales", "mpesa_receipt_number")
    op.drop_column("sales", "mpesa_phone_number")
    op.drop_column("sales", "mpesa_merchant_request_id")
    op.drop_column("sales", "mpesa_checkout_request_id")
