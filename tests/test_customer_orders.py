from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.main import app
from app.models import Product, Shop, Unit, User, UserRole, Variant


@pytest.fixture
def public_order_client() -> Generator[tuple[TestClient, int], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

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
        db.commit()
        variant_id = variant.id

    def override_db() -> Generator[Session, None, None]:
        with test_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: None
    try:
        yield TestClient(app), variant_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_public_order_is_created_with_human_readable_number(public_order_client):
    client, variant_id = public_order_client

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
