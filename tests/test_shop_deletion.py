from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import (
    BillingPayment,
    BillingPlan,
    Customer,
    CustomerOrder,
    CustomerOrderItem,
    CustomerPayment,
    MovementType,
    NotificationChannel,
    NotificationEvent,
    OrderFulfilment,
    OrderPaymentMethod,
    OrderReservation,
    PaymentMethod,
    Product,
    Sale,
    SaleItem,
    Shop,
    StockLot,
    StockLotAllocation,
    StockMovement,
    Unit,
    User,
    UserRole,
    Variant,
    VariantPriceHistory,
)
from app.schemas.shop import ShopDeleteRequest
from app.api.routes import shop as shop_routes


def test_delete_shop_removes_dependent_records(monkeypatch):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with test_session() as db:
        shop = Shop(name="Delete Test Shop")
        other_shop = Shop(name="Other Shop")
        db.add_all([shop, other_shop])
        db.flush()
        admin = User(
            shop_id=shop.id,
            full_name="Admin",
            username="delete_test_admin",
            password_hash="hashed",
            role=UserRole.ADMIN,
        )
        other_admin = User(
            shop_id=other_shop.id,
            full_name="Other Admin",
            username="other_delete_test_admin",
            password_hash="hashed",
            role=UserRole.ADMIN,
        )
        db.add_all([admin, other_admin])
        db.flush()

        product = Product(shop_id=shop.id, name="Test Product")
        db.add(product)
        db.flush()
        variant = Variant(
            product_id=product.id,
            name="Single",
            unit=Unit.PIECE,
            selling_price=Decimal("10.00"),
            cost_price=Decimal("5.00"),
            quantity=5,
        )
        customer = Customer(shop_id=shop.id, full_name="Test Customer")
        db.add_all([variant, customer])
        db.flush()

        sale = Sale(
            shop_id=shop.id,
            cashier_id=admin.id,
            subtotal=Decimal("10.00"),
            total=Decimal("10.00"),
            amount_received=Decimal("10.00"),
            change=Decimal("0.00"),
            customer_id=customer.id,
        )
        db.add(sale)
        db.flush()
        sale_item = SaleItem(
            sale_id=sale.id,
            variant_id=variant.id,
            variant_name=variant.name,
            quantity=1,
            unit_price=Decimal("10.00"),
            unit_cost_at_sale=Decimal("5.00"),
            line_total=Decimal("10.00"),
        )
        order = CustomerOrder(
            shop_id=shop.id,
            order_number="DT-1001",
            public_token="delete-test-order",
            fulfilment=OrderFulfilment.PICKUP,
            payment_method=OrderPaymentMethod.PAY_AT_PICKUP,
            customer_name="Test Customer",
            customer_phone="0712345678",
            subtotal=Decimal("10.00"),
            total=Decimal("10.00"),
            sale_id=sale.id,
        )
        db.add_all([sale_item, order])
        db.flush()
        db.add_all(
            [
                CustomerPayment(
                    shop_id=shop.id,
                    customer_id=customer.id,
                    sale_id=sale.id,
                    amount=Decimal("10.00"),
                    payment_method=PaymentMethod.CASH,
                    recorded_by_user_id=admin.id,
                ),
                CustomerOrderItem(
                    order_id=order.id,
                    variant_id=variant.id,
                    variant_name=variant.name,
                    quantity=1,
                    unit_price=Decimal("10.00"),
                    line_total=Decimal("10.00"),
                ),
                OrderReservation(
                    order_id=order.id,
                    variant_id=variant.id,
                    quantity=1,
                ),
                NotificationEvent(
                    shop_id=shop.id,
                    order_id=order.id,
                    channel=NotificationChannel.SMS,
                    event_type="order_created",
                    recipient="0712345678",
                    message="Order received",
                ),
                VariantPriceHistory(
                    variant_id=variant.id,
                    old_price=Decimal("9.00"),
                    new_price=Decimal("10.00"),
                    changed_by_user_id=admin.id,
                ),
            ]
        )
        movement = StockMovement(
            variant_id=variant.id,
            movement_type=MovementType.PURCHASE,
            quantity=5,
            previous_quantity=0,
            new_quantity=5,
            user_id=admin.id,
        )
        lot = StockLot(
            variant_id=variant.id,
            received_quantity=5,
            remaining_quantity=4,
            unit_cost=Decimal("5.00"),
        )
        plan = BillingPlan(code="delete-test", name="Delete Test", monthly_price=0)
        db.add_all([movement, lot, plan])
        db.flush()
        db.add_all(
            [
                StockLotAllocation(
                    lot_id=lot.id,
                    stock_movement_id=movement.id,
                    sale_item_id=sale_item.id,
                    quantity=1,
                    unit_cost=Decimal("5.00"),
                ),
                BillingPayment(
                    shop_id=shop.id,
                    user_id=admin.id,
                    plan_id=plan.id,
                    amount=Decimal("0.00"),
                    phone_number="0712345678",
                ),
            ]
        )
        db.commit()
        shop_id = shop.id
        other_shop_id = other_shop.id
        admin_id = admin.id

        monkeypatch.setattr(
            shop_routes, "verify_password", lambda plain, hashed: plain == "secret"
        )
        result = shop_routes.delete_shop(
            ShopDeleteRequest(shop_name=shop.name, current_password="secret"),
            db,
            admin,
        )

        assert result.status_code == 204
        assert db.get(Shop, shop_id) is None
        assert db.get(Shop, other_shop_id) is not None
        assert db.get(User, admin_id) is None
        assert db.get(User, other_admin.id) is not None

    Base.metadata.drop_all(engine)
    engine.dispose()
