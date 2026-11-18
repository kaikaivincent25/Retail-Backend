"""add feature suspensions and online store plan access

Revision ID: e1f3a5b7c9d1
Revises: f9a4c3d2e1b0
"""

from alembic import op
import sqlalchemy as sa


revision = "e1f3a5b7c9d1"
down_revision = "f9a4c3d2e1b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("suspended_features", sa.JSON(), nullable=False, server_default="[]"),
    )

    billing_plans = sa.table(
        "billing_plans",
        sa.column("code", sa.String()),
        sa.column("features", sa.JSON()),
    )
    connection = op.get_bind()
    plans = connection.execute(sa.select(billing_plans.c.code, billing_plans.c.features)).mappings()
    for plan in plans:
        features = dict(plan["features"] or {})
        features["online_store"] = plan["code"] in {"business", "pro"}
        connection.execute(
            billing_plans.update()
            .where(billing_plans.c.code == plan["code"])
            .values(features=features)
        )


def downgrade() -> None:
    billing_plans = sa.table(
        "billing_plans",
        sa.column("code", sa.String()),
        sa.column("features", sa.JSON()),
    )
    connection = op.get_bind()
    plans = connection.execute(sa.select(billing_plans.c.code, billing_plans.c.features)).mappings()
    for plan in plans:
        features = dict(plan["features"] or {})
        features.pop("online_store", None)
        connection.execute(
            billing_plans.update()
            .where(billing_plans.c.code == plan["code"])
            .values(features=features)
        )
    op.drop_column("subscriptions", "suspended_features")
