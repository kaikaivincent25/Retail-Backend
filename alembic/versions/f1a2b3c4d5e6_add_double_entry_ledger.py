"""add double-entry ledger

Revision ID: f1a2b3c4d5e6
Revises: c6d8e1f4a207
Create Date: 2026-11-07 15:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "c6d8e1f4a207"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')",
            name="ck_accounts_account_type",
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "code", name="uq_accounts_shop_code"),
    )
    op.create_index("ix_accounts_shop_id", "accounts", ["shop_id"])
    op.create_index(
        "ix_accounts_shop_active_code", "accounts", ["shop_id", "is_active", "code"]
    )

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id", "source_type", "source_id", name="uq_journal_entries_source"
        ),
    )
    op.create_index("ix_journal_entries_shop_id", "journal_entries", ["shop_id"])
    op.create_index(
        "ix_journal_entries_shop_date",
        "journal_entries",
        ["shop_id", "entry_date", "id"],
    )

    op.create_table(
        "journal_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("debit", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("credit", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="ck_journal_lines_one_positive_side",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_journal_lines_account"
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            ondelete="CASCADE",
            name="fk_journal_lines_entry",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_lines_journal_entry_id", "journal_lines", ["journal_entry_id"])
    op.create_index(
        "ix_journal_lines_account_entry", "journal_lines", ["account_id", "journal_entry_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_journal_lines_account_entry", table_name="journal_lines")
    op.drop_index("ix_journal_lines_journal_entry_id", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_journal_entries_shop_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_shop_id", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index("ix_accounts_shop_active_code", table_name="accounts")
    op.drop_index("ix_accounts_shop_id", table_name="accounts")
    op.drop_table("accounts")
