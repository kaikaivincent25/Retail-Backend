"""add billing plans and subscriptions

Revision ID: 9f2b7c1d4e6a
Revises: f7b236a8c940, ebb0b6a07dc7
Create Date: 2026-11-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f2b7c1d4e6a"
down_revision: Union[str, Sequence[str], None] = ("f7b236a8c940", "ebb0b6a07dc7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("monthly_price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("annual_price", sa.Integer(), nullable=True),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("code", name="uq_billing_plans_code"),
    )
    op.create_index("ix_billing_plans_code", "billing_plans", ["code"], unique=False)
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grace_period_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["billing_plans.id"]),
        sa.UniqueConstraint("shop_id", name="uq_subscriptions_shop_id"),
    )
    op.create_index("ix_subscriptions_shop_id", "subscriptions", ["shop_id"], unique=False)

    plans = sa.table(
        "billing_plans",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("monthly_price", sa.Integer),
        sa.column("annual_price", sa.Integer),
        sa.column("max_users", sa.Integer),
        sa.column("features", sa.JSON),
    )
    op.bulk_insert(plans, [
        {"code": "free", "name": "Free", "monthly_price": 0, "annual_price": 0, "max_users": 2,
         "features": {"reports.basic": True}},
        {"code": "starter", "name": "Starter", "monthly_price": 499, "annual_price": 4990, "max_users": 5,
         "features": {"reports.basic": True, "inventory.reports": True, "expenses": True}},
        {"code": "business", "name": "Business", "monthly_price": 999, "annual_price": 9990, "max_users": 15,
         "features": {"reports.basic": True, "reports.full": True, "reports.export": True, "inventory.reports": True,
                       "expenses": True, "mpesa.tools": True, "audit.logs": True}},
        {"code": "pro", "name": "Pro", "monthly_price": 1999, "annual_price": 19990, "max_users": 25,
         "features": {"reports.basic": True, "reports.full": True, "reports.export": True, "inventory.reports": True,
                       "expenses": True, "mpesa.tools": True, "audit.logs": True, "scheduled.reports": True,
                       "multi_branch": True}},
    ])
    op.execute(sa.text("""
        INSERT INTO subscriptions (shop_id, plan_id, status, current_period_start, current_period_end)
        SELECT s.id, p.id, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '100 years'
        FROM shops s CROSS JOIN billing_plans p
        WHERE p.code = 'free'
    """))


def downgrade() -> None:
    op.drop_index("ix_subscriptions_shop_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_billing_plans_code", table_name="billing_plans")
    op.drop_table("billing_plans")
