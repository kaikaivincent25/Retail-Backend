"""add customer credit and payments

Revision ID: b4c5d6e7f8a9
Revises: f1a2b3c4d5e6
Create Date: 2026-11-07 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add customer credit columns to sales
    op.add_column("sales", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column(
        "sales",
        sa.Column("is_credit", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("sales", sa.Column("due_date", sa.Date(), nullable=True))
    op.create_foreign_key(
        "fk_sales_customer_id",
        "sales",
        "customers",
        ["customer_id"],
        ["id"],
    )
    op.create_index("ix_sales_customer_id", "sales", ["customer_id"])
    op.create_index("ix_sales_shop_customer", "sales", ["shop_id", "customer_id"])
    op.create_index(
        "ix_sales_shop_credit_due", "sales", ["shop_id", "is_credit", "due_date"]
    )

    # 2. Create customer_payments table
    op.create_table(
        "customer_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("payment_method", sa.String(length=20), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_customer_payments_amount_positive"),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name="fk_customer_payments_customer"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"], ["users.id"], name="fk_customer_payments_user"
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"], ["sales.id"], name="fk_customer_payments_sale"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["cash_sessions.id"],
            name="fk_customer_payments_session",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name="fk_customer_payments_shop"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_payments_shop_id", "customer_payments", ["shop_id"])
    op.create_index(
        "ix_customer_payments_customer_id", "customer_payments", ["customer_id"]
    )
    op.create_index("ix_customer_payments_sale_id", "customer_payments", ["sale_id"])
    op.create_index(
        "ix_customer_payments_session_id", "customer_payments", ["session_id"]
    )
    op.create_index(
        "ix_customer_payments_shop_customer",
        "customer_payments",
        ["shop_id", "customer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_payments_shop_customer", table_name="customer_payments"
    )
    op.drop_index("ix_customer_payments_session_id", table_name="customer_payments")
    op.drop_index("ix_customer_payments_sale_id", table_name="customer_payments")
    op.drop_index("ix_customer_payments_customer_id", table_name="customer_payments")
    op.drop_index("ix_customer_payments_shop_id", table_name="customer_payments")
    op.drop_table("customer_payments")

    op.drop_index("ix_sales_shop_credit_due", table_name="sales")
    op.drop_index("ix_sales_shop_customer", table_name="sales")
    op.drop_index("ix_sales_customer_id", table_name="sales")
    op.drop_constraint("fk_sales_customer_id", "sales", type_="foreignkey")
    op.drop_column("sales", "due_date")
    op.drop_column("sales", "is_credit")
    op.drop_column("sales", "customer_id")
