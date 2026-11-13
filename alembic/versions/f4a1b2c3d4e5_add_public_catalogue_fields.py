"""add public catalogue fields"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f4a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = ("a1c8d9e4f260", "c8d9e0f1a2b3")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("slug", sa.String(length=160), nullable=True))
    op.create_index("ix_shops_slug", "shops", ["slug"], unique=False)
    op.execute(
        "UPDATE shops SET slug = trim(both '-' from regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g')) WHERE slug IS NULL"
    )
    op.create_unique_constraint("uq_shops_slug", "shops", ["slug"])
    op.add_column("products", sa.Column("is_public", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("products", sa.Column("public_name", sa.String(length=150), nullable=True))
    op.add_column("products", sa.Column("public_description", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("public_image_url", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("availability_message", sa.String(length=255), nullable=True))
    op.create_index("ix_products_is_public", "products", ["is_public"], unique=False)
    op.create_table(
        "customer_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("order_number", sa.String(length=24), nullable=False),
        sa.Column("public_token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Enum("pending", "accepted", "rejected", "preparing", "ready_for_pickup", "out_for_delivery", "delivered", "completed", "cancelled", name="customer_order_status"), nullable=False),
        sa.Column("fulfilment", sa.Enum("delivery", "pickup", name="order_fulfilment"), nullable=False),
        sa.Column("payment_method", sa.Enum("pay_on_delivery", "pay_at_pickup", "manual_mpesa", name="order_payment_method"), nullable=False),
        sa.Column("payment_status", sa.Enum("pending", "initiated", "paid", "failed", "refunded", name="order_payment_status"), nullable=False),
        sa.Column("mpesa_checkout_request_id", sa.String(length=100), nullable=True),
        sa.Column("mpesa_merchant_request_id", sa.String(length=100), nullable=True),
        sa.Column("mpesa_phone_number", sa.String(length=12), nullable=True),
        sa.Column("mpesa_receipt_number", sa.String(length=30), nullable=True),
        sa.Column("customer_name", sa.String(length=150), nullable=False),
        sa.Column("customer_phone", sa.String(length=30), nullable=False),
        sa.Column("delivery_address", sa.Text(), nullable=True),
        sa.Column("estate", sa.String(length=150), nullable=True),
        sa.Column("landmark", sa.String(length=255), nullable=True),
        sa.Column("delivery_instructions", sa.Text(), nullable=True),
        sa.Column("preferred_delivery_time", sa.String(length=100), nullable=True),
        sa.Column("shop_note", sa.Text(), nullable=True),
        sa.Column("subtotal", sa.Numeric(10, 2), nullable=False),
        sa.Column("total", sa.Numeric(10, 2), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=True),
        sa.Column("customer_notified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_token", name="uq_customer_orders_public_token"),
        sa.UniqueConstraint("shop_id", "order_number", name="uq_customer_orders_shop_number"),
        sa.UniqueConstraint("sale_id", name="uq_customer_orders_sale_id"),
        sa.UniqueConstraint("mpesa_checkout_request_id", name="uq_customer_orders_mpesa_checkout_request_id"),
        sa.UniqueConstraint("mpesa_receipt_number", name="uq_customer_orders_mpesa_receipt_number"),
    )
    op.create_index("ix_customer_orders_shop_id", "customer_orders", ["shop_id"])
    op.create_index("ix_customer_orders_public_token", "customer_orders", ["public_token"])
    op.create_index("ix_customer_orders_status", "customer_orders", ["status"])
    op.create_table(
        "order_reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("active", "released", "consumed", name="reservation_status"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["customer_orders.id"]),
        sa.ForeignKeyConstraint(["variant_id"], ["variants.id"]),
        sa.ForeignKeyConstraint(["released_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "variant_id", name="uq_order_reservations_order_variant"),
    )
    op.create_index("ix_order_reservations_order_id", "order_reservations", ["order_id"])
    op.create_index("ix_order_reservations_variant_id", "order_reservations", ["variant_id"])
    op.create_index("ix_order_reservations_status", "order_reservations", ["status"])
    op.create_index("ix_order_reservations_expires_at", "order_reservations", ["expires_at"])
    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.Enum("whatsapp", "sms", name="notification_channel"), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("recipient", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.Enum("pending", "sent", "failed", name="notification_status"), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_message_id", sa.String(length=150), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["customer_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_events_shop_id", "notification_events", ["shop_id"])
    op.create_index("ix_notification_events_order_id", "notification_events", ["order_id"])
    op.create_index("ix_notification_events_event_type", "notification_events", ["event_type"])
    op.create_index("ix_notification_events_status", "notification_events", ["status"])
    op.create_table(
        "customer_order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=False),
        sa.Column("variant_name", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["customer_orders.id"]),
        sa.ForeignKeyConstraint(["variant_id"], ["variants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_order_items_order_id", "customer_order_items", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_events_status", table_name="notification_events")
    op.drop_index("ix_notification_events_event_type", table_name="notification_events")
    op.drop_index("ix_notification_events_order_id", table_name="notification_events")
    op.drop_index("ix_notification_events_shop_id", table_name="notification_events")
    op.drop_table("notification_events")
    op.execute("DROP TYPE IF EXISTS notification_status")
    op.execute("DROP TYPE IF EXISTS notification_channel")
    op.drop_index("ix_order_reservations_expires_at", table_name="order_reservations")
    op.drop_index("ix_order_reservations_status", table_name="order_reservations")
    op.drop_index("ix_order_reservations_variant_id", table_name="order_reservations")
    op.drop_index("ix_order_reservations_order_id", table_name="order_reservations")
    op.drop_table("order_reservations")
    op.execute("DROP TYPE IF EXISTS reservation_status")
    op.drop_index("ix_customer_order_items_order_id", table_name="customer_order_items")
    op.drop_table("customer_order_items")
    op.drop_index("ix_customer_orders_status", table_name="customer_orders")
    op.drop_index("ix_customer_orders_public_token", table_name="customer_orders")
    op.drop_index("ix_customer_orders_shop_id", table_name="customer_orders")
    op.drop_table("customer_orders")
    op.execute("DROP TYPE IF EXISTS order_payment_status")
    op.execute("DROP TYPE IF EXISTS order_payment_method")
    op.execute("DROP TYPE IF EXISTS order_fulfilment")
    op.execute("DROP TYPE IF EXISTS customer_order_status")
    op.drop_index("ix_products_is_public", table_name="products")
    for column in ("availability_message", "public_image_url", "public_description", "public_name", "is_public"):
        op.drop_column("products", column)
    op.drop_constraint("uq_shops_slug", "shops", type_="unique")
    op.drop_index("ix_shops_slug", table_name="shops")
    op.drop_column("shops", "slug")
