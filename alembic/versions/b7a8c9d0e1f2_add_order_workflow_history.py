"""add order workflow history and payment records

Revision ID: b7a8c9d0e1f2
Revises: a6c9d2e4f501
"""

from alembic import op
import sqlalchemy as sa


revision = "b7a8c9d0e1f2"
down_revision = "a6c9d2e4f501"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_orders",
        sa.Column("received_by_name", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "customer_orders",
        sa.Column("payment_reference", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "customer_orders",
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "customer_orders",
        sa.Column("paid_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_customer_orders_paid_by_user_id_users",
        "customer_orders",
        "users",
        ["paid_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_customer_orders_paid_by_user_id",
        "customer_orders",
        ["paid_by_user_id"],
    )
    op.execute(
        """
        UPDATE customer_orders AS customer_order
        SET payment_status = 'paid',
            paid_at = COALESCE(customer_order.paid_at, sale.created_at),
            paid_by_user_id = COALESCE(customer_order.paid_by_user_id, sale.cashier_id),
            payment_reference = COALESCE(
                customer_order.payment_reference,
                customer_order.mpesa_receipt_number
            )
        FROM sales AS sale
        WHERE customer_order.sale_id = sale.id
          AND customer_order.status = 'completed'
          AND customer_order.payment_status IN ('pending', 'paid')
        """
    )
    op.add_column(
        "customers",
        sa.Column(
            "identity_review_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.execute(
        """
        DO $$
        DECLARE
            phone_group RECORD;
            first_order RECORD;
            anonymous_order RECORD;
            active_match_count INTEGER;
            matched_customer_id INTEGER;
            created_customer_id INTEGER;
        BEGIN
            FOR phone_group IN
                SELECT shop_id, customer_phone_normalized
                FROM customer_orders
                WHERE customer_id IS NULL
                  AND customer_phone_normalized IS NOT NULL
                GROUP BY shop_id, customer_phone_normalized
            LOOP
                SELECT count(*), min(id)
                INTO active_match_count, matched_customer_id
                FROM customers
                WHERE shop_id = phone_group.shop_id
                  AND phone_normalized = phone_group.customer_phone_normalized
                  AND is_active = true;

                IF active_match_count = 1 THEN
                    UPDATE customer_orders
                    SET customer_id = matched_customer_id
                    WHERE shop_id = phone_group.shop_id
                      AND customer_phone_normalized = phone_group.customer_phone_normalized
                      AND customer_id IS NULL;
                ELSE
                    SELECT customer_name, customer_phone
                    INTO first_order
                    FROM customer_orders
                    WHERE shop_id = phone_group.shop_id
                      AND customer_phone_normalized = phone_group.customer_phone_normalized
                      AND customer_id IS NULL
                    ORDER BY created_at, id
                    LIMIT 1;

                    INSERT INTO customers (
                        shop_id, full_name, phone, phone_normalized,
                        identity_review_required
                    )
                    VALUES (
                        phone_group.shop_id,
                        first_order.customer_name,
                        first_order.customer_phone,
                        phone_group.customer_phone_normalized,
                        active_match_count > 1
                    )
                    RETURNING id INTO created_customer_id;

                    UPDATE customer_orders
                    SET customer_id = created_customer_id
                    WHERE shop_id = phone_group.shop_id
                      AND customer_phone_normalized = phone_group.customer_phone_normalized
                      AND customer_id IS NULL;
                END IF;
            END LOOP;

            FOR anonymous_order IN
                SELECT id, shop_id, customer_name, customer_phone
                FROM customer_orders
                WHERE customer_id IS NULL
                  AND customer_phone_normalized IS NULL
                ORDER BY id
            LOOP
                INSERT INTO customers (shop_id, full_name, phone)
                VALUES (
                    anonymous_order.shop_id,
                    anonymous_order.customer_name,
                    anonymous_order.customer_phone
                )
                RETURNING id INTO created_customer_id;

                UPDATE customer_orders
                SET customer_id = created_customer_id
                WHERE id = anonymous_order.id;
            END LOOP;
        END
        $$;
        """
    )

    op.create_table(
        "customer_order_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["customer_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_order_events_order_created",
        "customer_order_events",
        ["order_id", "created_at"],
    )
    op.create_index(
        "ix_customer_order_events_shop_created",
        "customer_order_events",
        ["shop_id", "created_at"],
    )
    op.execute(
        """
        INSERT INTO customer_order_events (
            order_id, shop_id, actor_user_id, event_type, from_status,
            to_status, details, created_at, updated_at
        )
        SELECT
            customer_order.id,
            customer_order.shop_id,
            customer_order.paid_by_user_id,
            'payment_confirmed',
            NULL,
            NULL,
            'Payment imported from the existing completed order sale.',
            customer_order.paid_at,
            customer_order.paid_at
        FROM customer_orders AS customer_order
        WHERE customer_order.paid_at IS NOT NULL
          AND customer_order.status = 'completed'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_order_events_shop_created", table_name="customer_order_events"
    )
    op.drop_index(
        "ix_customer_order_events_order_created", table_name="customer_order_events"
    )
    op.drop_table("customer_order_events")
    op.drop_column("customers", "identity_review_required")
    op.drop_index("ix_customer_orders_paid_by_user_id", table_name="customer_orders")
    op.drop_constraint(
        "fk_customer_orders_paid_by_user_id_users",
        "customer_orders",
        type_="foreignkey",
    )
    op.drop_column("customer_orders", "paid_by_user_id")
    op.drop_column("customer_orders", "paid_at")
    op.drop_column("customer_orders", "payment_reference")
    op.drop_column("customer_orders", "received_by_name")
