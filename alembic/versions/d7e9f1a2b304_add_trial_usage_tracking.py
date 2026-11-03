"""add trial usage tracking

Revision ID: d7e9f1a2b304
Revises: c8d4e6f1a203
"""

from alembic import op
import sqlalchemy as sa


revision = "d7e9f1a2b304"
down_revision = "c8d4e6f1a203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("trial_used", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("UPDATE subscriptions SET trial_used = true WHERE trial_ends_at IS NOT NULL OR status = 'trialing'"))


def downgrade() -> None:
    op.drop_column("subscriptions", "trial_used")
