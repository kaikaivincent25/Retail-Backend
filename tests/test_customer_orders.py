from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    CashSession,
    Customer,
    CustomerOrder,
    Product,
    Sale,
    Shop,
    StockLot,
    Unit,
    User,
    UserRole,
    Variant,
)
from app.models.cash_session import SessionStatus
from app.models.billing import BillingPlan, Subscription, SubscriptionStatus
from app.models.customer_order import OrderPaymentStatus
from app.core.business_time import (
    BUSINESS_TIMEZONE,
    business_day_bounds,
    business_today,
)
from app.services.cash_sessions import auto_close_expired_sessions


@pytest.fixture
def public_order_client() -> Generator[tuple[TestClient, int, sessionmaker], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    with test_session() as db:
        shop = Shop(name="Order Test Shop", slug="order-test")
        db.add(shop)
        db.flush()
        plan = BillingPlan(code="business", name="Business", monthly_price=999, features={"online_store": True})
        db.add(plan)
        db.flush()
        now = datetime.now(timezone.utc)
        db.add(Subscription(
            shop_id=shop.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        ))
        product = Product(
            shop_id=shop.id,
            name="Test Product",
            is_public=True,
        )
        db.add(product)
        db.flush()
        variant = Variant(
            product_id=product.id,
            name="Single",
            unit=Unit.PIECE,
            selling_price="25.00",
            cost_price="10.00",
            cost_price_is_known=True,
            quantity=10,
        )
        db.add(variant)
        cashier = User(
            shop_id=shop.id,
            full_name="Order Test Cashier",
            username="order_test_cashier",
            password_hash="unused",
            role=UserRole.CASHIER,
        )
        db.add(cashier)
        db.commit()
        variant_id = variant.id
        active_user = {"user": cashier}

    def override_db() -> Generator[Session, None, None]:
        with test_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: active_user["user"]
    try:
        yield TestClient(app), variant_id, test_session
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_public_order_is_created_with_human_readable_number(public_order_client):
    client, variant_id, test_session = public_order_client

    response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 2}],
            "customer_name": "Amina Otieno",
            "customer_phone": "0712345678",
            "fulfilment": "delivery",
            "payment_method": "pay_on_delivery",
            "delivery_address": "Town centre",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["order_number"] == "OR-1001"
    assert body["items"][0]["quantity"] == 2
    assert body["total"] == "50.00"
    with test_session() as db:
        order = db.query(CustomerOrder).filter_by(order_number=body["order_number"]).one()
        customer = db.query(Customer).filter_by(id=order.customer_id).one()
        assert customer.full_name == "Amina Otieno"
        assert customer.phone_normalized == "254712345678"


def test_business_day_bounds_use_nairobi_midnight():
    start, end = business_day_bounds(date(2026, 11, 19))

    assert start == datetime(2026, 11, 18, 21, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 19, 21, 0, tzinfo=timezone.utc)


def test_auto_close_uses_provisional_expected_cash_and_carries_it_forward(public_order_client):
    client, _, test_session = public_order_client
    with test_session() as db:
        shop = db.query(Shop).filter_by(slug="order-test").one()
        user = db.query(User).filter_by(username="order_test_cashier").one()
        session = CashSession(
            shop_id=shop.id,
            user_id=user.id,
            opening_cash=Decimal("125.00"),
            status=SessionStatus.OPEN,
            created_at=datetime(2026, 1, 1, 20, 59, tzinfo=timezone.utc),
        )
        db.add(session)
        db.commit()

        assert auto_close_expired_sessions(
            db,
            now=datetime(2026, 1, 2, 0, 0, 30, tzinfo=BUSINESS_TIMEZONE),
        ) == 1
        db.refresh(session)
        assert session.status == SessionStatus.CLOSED
        assert session.closing_cash == 125
        assert session.expected_cash == 125
        assert session.auto_closed is True

    opened = client.post("/cash-sessions/open", json={})
    assert opened.status_code == 201, opened.text
    assert opened.json()["opening_cash"] == "125.00"


def test_public_order_links_one_customer_with_matching_normalized_phone(public_order_client):
    client, variant_id, test_session = public_order_client
    customer_response = client.post(
        "/customers",
        json={"full_name": "Existing Customer", "phone": "0712345678"},
    )
    assert customer_response.status_code == 201, customer_response.text
    customer_id = customer_response.json()["id"]

    response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 1}],
            "customer_name": "Amina Otieno",
            "customer_phone": "+254 712 345 678",
            "fulfilment": "delivery",
            "payment_method": "pay_on_delivery",
            "delivery_address": "Town centre",
        },
    )
    assert response.status_code == 201, response.text
    with test_session() as db:
        order = db.query(CustomerOrder).filter_by(order_number=response.json()["order_number"]).one()
        assert order.customer_id == customer_id


def test_public_order_creates_reviewable_profile_for_duplicate_customer_phones(public_order_client):
    client, variant_id, test_session = public_order_client
    with test_session() as db:
        shop = db.query(Shop).filter_by(slug="order-test").one()
        db.add_all(
            [
                Customer(
                    shop_id=shop.id,
                    full_name="Customer One",
                    phone="0712345678",
                    phone_normalized="254712345678",
                ),
                Customer(
                    shop_id=shop.id,
                    full_name="Customer Two",
                    phone="+254712345678",
                    phone_normalized="254712345678",
                ),
            ]
        )
        db.commit()

    response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 1}],
            "customer_name": "Amina Otieno",
            "customer_phone": "0712345678",
            "fulfilment": "delivery",
            "payment_method": "pay_on_delivery",
            "delivery_address": "Town centre",
        },
    )
    assert response.status_code == 201, response.text
    with test_session() as db:
        order = db.query(CustomerOrder).filter_by(order_number=response.json()["order_number"]).one()
        customer = db.query(Customer).filter_by(id=order.customer_id).one()
        assert customer.id not in {
            customer.id
            for customer in db.query(Customer)
            .filter_by(phone_normalized="254712345678")
            .all()
            if customer.full_name in {"Customer One", "Customer Two"}
        }
        assert customer.identity_review_required is True


def test_public_order_customer_profile_is_not_replaced_by_a_later_manual_profile(public_order_client):
    client, variant_id, test_session = public_order_client
    order_response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 1}],
            "customer_name": "Amina Otieno",
            "customer_phone": "0712345678",
            "fulfilment": "delivery",
            "payment_method": "pay_on_delivery",
            "delivery_address": "Town centre",
        },
    )
    assert order_response.status_code == 201, order_response.text
    with test_session() as db:
        original_order = db.query(CustomerOrder).filter_by(
            order_number=order_response.json()["order_number"]
        ).one()
        original_customer_id = original_order.customer_id

    customer_response = client.post(
        "/customers",
        json={"full_name": "Amina Otieno", "phone": "+254 712 345 678"},
    )
    assert customer_response.status_code == 201, customer_response.text
    with test_session() as db:
        order = db.query(CustomerOrder).filter_by(order_number=order_response.json()["order_number"]).one()
        assert order.customer_id == original_customer_id
        assert order.customer_id != customer_response.json()["id"]


def test_order_fulfilment_requires_recipient_and_payment_before_closing(public_order_client):
    client, variant_id, test_session = public_order_client
    with test_session() as db:
        db.add(
            StockLot(
                variant_id=variant_id,
                received_quantity=10,
                remaining_quantity=10,
                unit_cost="10.00",
            )
        )
        db.commit()
    response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 1}],
            "customer_name": "Amina Otieno",
            "customer_phone": "0712345678",
            "fulfilment": "delivery",
            "payment_method": "pay_on_delivery",
            "delivery_address": "Town centre",
        },
    )
    assert response.status_code == 201, response.text
    order = client.get("/orders").json()[0]

    dashboard = client.get("/dashboard/cashier-summary")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["pending_orders_count"] == 1
    assert dashboard.json()["orders_awaiting_payment_count"] == 1
    assert dashboard.json()["recent_orders"][0]["order_number"] == order["order_number"]

    for next_status in ("accepted", "preparing", "out_for_delivery"):
        update = client.patch(f"/orders/{order['id']}", json={"status": next_status})
        assert update.status_code == 200, update.text

    missing_recipient = client.patch(
        f"/orders/{order['id']}",
        json={"status": "delivered"},
    )
    assert missing_recipient.status_code == 422

    delivered = client.patch(
        f"/orders/{order['id']}",
        json={"status": "delivered", "received_by_name": "Amina Otieno"},
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["received_by_name"] == "Amina Otieno"

    unpaid_close = client.patch(
        f"/orders/{order['id']}",
        json={"status": "completed"},
    )
    assert unpaid_close.status_code == 409

    no_till_payment = client.post(
        f"/orders/{order['id']}/payment/record",
        json={"reference": "CASH-001"},
    )
    assert no_till_payment.status_code == 422
    opened_session = client.post("/cash-sessions/open", json={})
    assert opened_session.status_code == 201, opened_session.text

    paid = client.post(
        f"/orders/{order['id']}/payment/record",
        json={"reference": "CASH-001"},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["payment_status"] == "paid"
    assert paid.json()["payment_reference"] == "CASH-001"
    current_session = client.get("/cash-sessions/current")
    assert current_session.status_code == 200
    assert current_session.json()["cash_sales_total"] == "25.00"
    assert current_session.json()["non_cash_sales_total"] == "0.00"
    assert current_session.json()["sales_total"] == "25.00"

    completed = client.patch(
        f"/orders/{order['id']}",
        json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["sale_id"] is not None
    with test_session() as db:
        sale = db.query(Sale).filter_by(id=completed.json()["sale_id"]).one()
        sale.created_at = business_day_bounds(business_today())[0] + timedelta(hours=1)
        db.commit()
    completed_day_summary = client.get("/dashboard/cashier-summary")
    assert completed_day_summary.status_code == 200, completed_day_summary.text
    assert completed_day_summary.json()["total_sales"] == "25.00"
    assert completed_day_summary.json()["transaction_count"] == 1

    history = client.get(f"/orders/{order['id']}/history")
    assert history.status_code == 200, history.text
    event_types = [event["event_type"] for event in history.json()]
    assert event_types.count("status_changed") == 5
    assert "payment_confirmed" in event_types
    assert history.json()[0]["event_type"] == "order_placed"

    with test_session() as db:
        persisted_order = db.query(CustomerOrder).filter_by(id=order["id"]).one()
        assert persisted_order.payment_status.value == "paid"
        assert persisted_order.paid_by_user_id is not None


def test_customer_order_history_endpoint_shows_linked_online_orders(public_order_client):
    client, variant_id, _ = public_order_client
    response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 1}],
            "customer_name": "Amina Otieno",
            "customer_phone": "0712345678",
            "fulfilment": "delivery",
            "payment_method": "pay_on_delivery",
            "delivery_address": "Town centre",
        },
    )
    assert response.status_code == 201, response.text
    order = client.get("/orders").json()[0]

    customer_orders = client.get(f"/customers/{order['customer_id']}/orders")
    assert customer_orders.status_code == 200, customer_orders.text
    assert [item["order_number"] for item in customer_orders.json()] == [order["order_number"]]


def test_manual_mpesa_confirmation_is_audited_and_cannot_be_overwritten(public_order_client):
    client, variant_id, _ = public_order_client
    response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 1}],
            "customer_name": "Amina Otieno",
            "customer_phone": "0712345678",
            "fulfilment": "delivery",
            "payment_method": "manual_mpesa",
            "delivery_address": "Town centre",
        },
    )
    assert response.status_code == 201, response.text
    order = client.get("/orders").json()[0]

    paid = client.post(
        f"/orders/{order['id']}/payment/confirm",
        params={"receipt_number": "RCP123"},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["payment_status"] == "paid"
    assert paid.json()["payment_reference"] == "RCP123"
    assert paid.json()["paid_by_user_id"] is not None

    conflicting_receipt = client.post(
        f"/orders/{order['id']}/payment/confirm",
        params={"receipt_number": "RCP456"},
    )
    assert conflicting_receipt.status_code == 409


def test_paid_online_order_counts_in_daily_sales_and_non_cash_session_total(
    public_order_client,
):
    client, variant_id, test_session = public_order_client
    with test_session() as db:
        db.add(
            StockLot(
                variant_id=variant_id,
                received_quantity=10,
                remaining_quantity=10,
                unit_cost="10.00",
            )
        )
        db.commit()
    response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 1}],
            "customer_name": "Amina Otieno",
            "customer_phone": "0712345678",
            "fulfilment": "delivery",
            "payment_method": "manual_mpesa",
            "delivery_address": "Town centre",
        },
    )
    assert response.status_code == 201, response.text
    order = client.get("/orders").json()[0]

    opened = client.post("/cash-sessions/open", json={})
    assert opened.status_code == 201, opened.text
    paid = client.post(
        f"/orders/{order['id']}/payment/confirm",
        params={"receipt_number": "RCP789"},
    )
    assert paid.status_code == 200, paid.text

    session = client.get("/cash-sessions/current").json()
    assert session["cash_sales_total"] == "0.00"
    assert session["non_cash_sales_total"] == "25.00"
    assert session["sales_total"] == "25.00"
    assert session["expected_cash"] == "0.00"

    summary = client.get("/dashboard/cashier-summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["total_sales"] == "25.00"
    assert summary.json()["transaction_count"] == 1

    for next_status in ("accepted", "preparing", "out_for_delivery"):
        changed = client.patch(
            f"/orders/{order['id']}",
            json={"status": next_status},
        )
        assert changed.status_code == 200, changed.text
    delivered = client.patch(
        f"/orders/{order['id']}",
        json={"status": "delivered", "received_by_name": "Amina Otieno"},
    )
    assert delivered.status_code == 200, delivered.text
    completed = client.patch(
        f"/orders/{order['id']}",
        json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text

    summary_after_completion = client.get("/dashboard/cashier-summary")
    assert summary_after_completion.json()["total_sales"] == "25.00"
    assert summary_after_completion.json()["transaction_count"] == 1


def test_customer_can_cancel_an_unpaid_order(public_order_client):
    client, variant_id, _ = public_order_client
    response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 1}],
            "customer_name": "Amina Otieno",
            "customer_phone": "0712345678",
            "fulfilment": "delivery",
            "payment_method": "pay_on_delivery",
            "delivery_address": "Town centre",
        },
    )
    assert response.status_code == 201, response.text

    cancelled = client.post(f"/public/orders/{response.json()['public_token']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert client.get(f"/public/orders/{response.json()['public_token']}").json()["status"] == "cancelled"


def test_customer_cannot_cancel_while_mpesa_payment_is_in_progress(public_order_client):
    client, variant_id, test_session = public_order_client
    response = client.post(
        "/public/shops/order-test/orders",
        json={
            "items": [{"variant_id": variant_id, "quantity": 1}],
            "customer_name": "Amina Otieno",
            "customer_phone": "0712345678",
            "fulfilment": "delivery",
            "payment_method": "manual_mpesa",
            "delivery_address": "Town centre",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["public_token"]
    with test_session() as db:
        order = db.query(CustomerOrder).filter_by(public_token=token).one()
        order.payment_status = OrderPaymentStatus.INITIATED
        db.commit()

    cancelled = client.post(f"/public/orders/{token}/cancel")
    assert cancelled.status_code == 409
    assert "payment is still in progress" in cancelled.json()["detail"]
