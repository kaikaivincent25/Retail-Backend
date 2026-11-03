"""add billing payment records

Revision ID: c8d4e6f1a203
Revises: 84a3798b914e
"""

from alembic import op
import sqlalchemy as sa


revision = "c8d4e6f1a203"
down_revision = "84a3798b914e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("phone_number", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("checkout_request_id", sa.String(length=100), nullable=True),
        sa.Column("merchant_request_id", sa.String(length=100), nullable=True),
        sa.Column("receipt_number", sa.String(length=30), nullable=True),
        sa.Column("provider_result_code", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["billing_plans.id"]),
        sa.UniqueConstraint("checkout_request_id", name="uq_billing_payments_checkout_request_id"),
    )
    op.create_index("ix_billing_payments_shop_id", "billing_payments", ["shop_id"])


def downgrade() -> None:
    op.drop_index("ix_billing_payments_shop_id", table_name="billing_payments")
    op.drop_table("billing_payments")
