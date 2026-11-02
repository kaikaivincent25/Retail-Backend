"""add platform owner access and shop suspension

Revision ID: a14c5e8f9b22
Revises: 9f2b7c1d4e6a
Create Date: 2026-11-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a14c5e8f9b22"
down_revision: Union[str, Sequence[str], None] = "9f2b7c1d4e6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("is_suspended", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "platform_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("username", name="uq_platform_users_username"),
    )
    op.create_index("ix_platform_users_username", "platform_users", ["username"], unique=False)
    op.create_table(
        "platform_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("platform_user_id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["platform_user_id"], ["platform_users.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_platform_audit_logs_platform_user_id", "platform_audit_logs", ["platform_user_id"], unique=False)
    op.create_index("ix_platform_audit_logs_shop_id", "platform_audit_logs", ["shop_id"], unique=False)
    op.create_index("ix_platform_audit_logs_action", "platform_audit_logs", ["action"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_platform_audit_logs_action", table_name="platform_audit_logs")
    op.drop_index("ix_platform_audit_logs_shop_id", table_name="platform_audit_logs")
    op.drop_index("ix_platform_audit_logs_platform_user_id", table_name="platform_audit_logs")
    op.drop_table("platform_audit_logs")
    op.drop_index("ix_platform_users_username", table_name="platform_users")
    op.drop_table("platform_users")
    op.drop_column("shops", "is_suspended")
