"""add short customer order tracking codes

Revision ID: f5d8a1c3e6b2
Revises: da30e8b17c42
"""

import secrets

from alembic import op
import sqlalchemy as sa


revision = "f5d8a1c3e6b2"
down_revision = "da30e8b17c42"
branch_labels = None
depends_on = None

TRACKING_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TRACKING_CODE_LENGTH = 12


def _new_tracking_code(bind) -> str:
    while True:
        code = "".join(
            secrets.choice(TRACKING_CODE_ALPHABET)
            for _ in range(TRACKING_CODE_LENGTH)
        )
        exists = bind.execute(
            sa.text("SELECT 1 FROM customer_orders WHERE tracking_code = :code"),
            {"code": code},
        ).scalar()
        if exists is None:
            return code


def upgrade() -> None:
    op.add_column(
        "customer_orders",
        sa.Column("tracking_code", sa.String(length=12), nullable=True),
    )
    bind = op.get_bind()
    order_ids = bind.execute(
        sa.text("SELECT id FROM customer_orders WHERE tracking_code IS NULL")
    ).scalars().all()
    for order_id in order_ids:
        bind.execute(
            sa.text(
                "UPDATE customer_orders SET tracking_code = :code WHERE id = :order_id"
            ),
            {"code": _new_tracking_code(bind), "order_id": order_id},
        )
    op.alter_column("customer_orders", "tracking_code", nullable=False)
    op.create_unique_constraint(
        "uq_customer_orders_tracking_code",
        "customer_orders",
        ["tracking_code"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_customer_orders_tracking_code",
        "customer_orders",
        type_="unique",
    )
    op.drop_column("customer_orders", "tracking_code")
