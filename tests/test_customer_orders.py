from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.main import app
from app.models import Customer, CustomerOrder, Product, Shop, Unit, User, UserRole, Variant


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
    client, variant_id, _ = public_order_client

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


def test_public_order_does_not_guess_between_duplicate_customer_phones(public_order_client):
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
        assert order.customer_id is None


def test_adding_customer_links_earlier_guest_orders(public_order_client):
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

    customer_response = client.post(
        "/customers",
        json={"full_name": "Amina Otieno", "phone": "+254 712 345 678"},
    )
    assert customer_response.status_code == 201, customer_response.text
    with test_session() as db:
        order = db.query(CustomerOrder).filter_by(order_number=order_response.json()["order_number"]).one()
        assert order.customer_id == customer_response.json()["id"]
