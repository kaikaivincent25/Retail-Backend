"""add post-close cash session reconciliation

Revision ID: 2b3c4d5e6f70
Revises: 1a2b3c4d5e6f
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "2b3c4d5e6f70"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("cash_sessions", sa.Column("recount_reason", sa.String(length=255), nullable=True))
    op.add_column("cash_sessions", sa.Column("recounted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cash_sessions", sa.Column("recounted_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_cash_sessions_recounted_by_user_id_users",
        "cash_sessions", "users", ["recounted_by_user_id"], ["id"],
    )

def downgrade() -> None:
    op.drop_constraint("fk_cash_sessions_recounted_by_user_id_users", "cash_sessions", type_="foreignkey")
    op.drop_column("cash_sessions", "recounted_by_user_id")
    op.drop_column("cash_sessions", "recounted_at")
    op.drop_column("cash_sessions", "recount_reason")
