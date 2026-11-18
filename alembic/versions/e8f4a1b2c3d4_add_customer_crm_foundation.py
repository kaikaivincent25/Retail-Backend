"""add customer CRM foundation"""

from alembic import op
import sqlalchemy as sa


revision = "e8f4a1b2c3d4"
down_revision = "c4e8a7b19d32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("phone_normalized", sa.String(length=15), nullable=True))
    op.add_column(
        "customers",
        sa.Column("lead_status", sa.String(length=20), nullable=False, server_default="new"),
    )
    op.create_check_constraint(
        "ck_customers_lead_status",
        "customers",
        "lead_status IN ('new', 'contacted', 'interested', 'won', 'lost')",
    )
    op.create_index(
        "ix_customers_shop_phone_normalized",
        "customers",
        ["shop_id", "phone_normalized"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            UPDATE customers AS customer
            SET phone_normalized = CASE
                WHEN length(phone.digits) = 10 AND left(phone.digits, 1) = '0'
                    THEN '254' || substr(phone.digits, 2)
                WHEN length(phone.digits) = 9 AND left(phone.digits, 1) IN ('1', '7')
                    THEN '254' || phone.digits
                WHEN length(phone.digits) BETWEEN 9 AND 15 AND left(phone.digits, 1) <> '0'
                    THEN phone.digits
                ELSE NULL
            END
            FROM (
                SELECT id, regexp_replace(phone, '[^0-9]', '', 'g') AS digits
                FROM customers
                WHERE phone IS NOT NULL
            ) AS phone
            WHERE customer.id = phone.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE customers
            SET lead_status = 'won'
            WHERE EXISTS (
                SELECT 1
                FROM sales
                WHERE sales.customer_id = customers.id
                  AND sales.shop_id = customers.shop_id
                  AND sales.status = 'completed'
            )
            """
        )
    )

    op.add_column(
        "customer_orders",
        sa.Column("customer_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "customer_orders",
        sa.Column("customer_phone_normalized", sa.String(length=15), nullable=True),
    )
    op.create_index(
        "ix_customer_orders_shop_phone_normalized",
        "customer_orders",
        ["shop_id", "customer_phone_normalized"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE customer_orders AS customer_order
            SET customer_phone_normalized = CASE
                WHEN length(phone.digits) = 10 AND left(phone.digits, 1) = '0'
                    THEN '254' || substr(phone.digits, 2)
                WHEN length(phone.digits) = 9 AND left(phone.digits, 1) IN ('1', '7')
                    THEN '254' || phone.digits
                WHEN length(phone.digits) BETWEEN 9 AND 15 AND left(phone.digits, 1) <> '0'
                    THEN phone.digits
                ELSE NULL
            END
            FROM (
                SELECT id, regexp_replace(customer_phone, '[^0-9]', '', 'g') AS digits
                FROM customer_orders
            ) AS phone
            WHERE customer_order.id = phone.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE customer_orders AS customer_order
            SET customer_id = matches.customer_id
            FROM (
                SELECT customer_order.id, min(customer.id) AS customer_id
                FROM customer_orders AS customer_order
                JOIN customers AS customer
                  ON customer.shop_id = customer_order.shop_id
                 AND customer.phone_normalized = customer_order.customer_phone_normalized
                 AND customer.is_active = true
                WHERE customer_order.customer_id IS NULL
                  AND customer_order.customer_phone_normalized IS NOT NULL
                GROUP BY customer_order.id
                HAVING count(customer.id) = 1
            ) AS matches
            WHERE customer_order.id = matches.id
            """
        )
    )
    op.create_foreign_key(
        "fk_customer_orders_customer_id_customers",
        "customer_orders",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_customer_orders_customer_id", "customer_orders", ["customer_id"])

    op.create_table(
        "customer_activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("activity_type", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="completed", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("assigned_to_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "activity_type IN ('note', 'follow_up', 'lead_status')",
            name="ck_customer_activities_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'completed')",
            name="ck_customer_activities_status",
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["assigned_to_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_activities_shop_id", "customer_activities", ["shop_id"])
    op.create_index("ix_customer_activities_customer_id", "customer_activities", ["customer_id"])
    op.create_index(
        "ix_customer_activities_customer_created",
        "customer_activities",
        ["customer_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_customer_activities_customer_created", table_name="customer_activities")
    op.drop_index("ix_customer_activities_customer_id", table_name="customer_activities")
    op.drop_index("ix_customer_activities_shop_id", table_name="customer_activities")
    op.drop_table("customer_activities")
    op.drop_index("ix_customer_orders_customer_id", table_name="customer_orders")
    op.drop_constraint(
        "fk_customer_orders_customer_id_customers",
        "customer_orders",
        type_="foreignkey",
    )
    op.drop_column("customer_orders", "customer_id")
    op.drop_index("ix_customer_orders_shop_phone_normalized", table_name="customer_orders")
    op.drop_column("customer_orders", "customer_phone_normalized")
    op.drop_index("ix_customers_shop_phone_normalized", table_name="customers")
    op.drop_constraint("ck_customers_lead_status", "customers", type_="check")
    op.drop_column("customers", "lead_status")
    op.drop_column("customers", "phone_normalized")
