from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.api.deps import get_current_user
from app.main import app
from app.models import Customer, Shop, User, UserRole


@pytest.fixture
def customer_client() -> Generator[tuple[TestClient, User, User, int], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with test_session() as db:
        shop = Shop(name="Customer Test Shop")
        other_shop = Shop(name="Other Customer Test Shop")
        db.add_all([shop, other_shop])
        db.flush()
        cashier = User(
            shop_id=shop.id,
            full_name="Test Cashier",
            username="customer_test_cashier",
            password_hash="unused",
            role=UserRole.CASHIER,
        )
        manager = User(
            shop_id=shop.id,
            full_name="Test Manager",
            username="customer_test_manager",
            password_hash="unused",
            role=UserRole.MANAGER,
        )
        other_customer = Customer(shop_id=other_shop.id, full_name="Private Customer")
        db.add_all([cashier, manager, other_customer])
        db.commit()
        db.refresh(cashier)
        db.refresh(manager)
        other_customer_id = other_customer.id

    active_user = {"user": cashier}

    def override_db() -> Generator[Session, None, None]:
        with test_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: active_user["user"]
    try:
        yield TestClient(app), cashier, manager, other_customer_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_customers_are_shop_scoped_and_limits_are_manager_only(customer_client):
    client, cashier, manager, other_customer_id = customer_client
    created = client.post(
        "/customers",
        json={"full_name": "  A Customer  ", "phone": "  0712345678  "},
    )
    assert created.status_code == 201
    assert created.json()["full_name"] == "A Customer"
    assert created.json()["phone"] == "0712345678"
    assert created.json()["credit_limit"] is None

    assert client.get(f"/customers/{other_customer_id}").status_code == 404
    assert client.patch(
        f"/customers/{created.json()['id']}",
        json={"credit_limit": "1000.00"},
    ).status_code == 403

    app.dependency_overrides[get_current_user] = lambda: manager
    updated = client.patch(
        f"/customers/{created.json()['id']}",
        json={"credit_limit": "1000.00"},
    )
    assert updated.status_code == 200
    assert updated.json()["credit_limit"] == "1000.00"

    archived = client.patch(
        f"/customers/{created.json()['id']}",
        json={"is_active": False},
    )
    assert archived.status_code == 200
    assert client.get("/customers").json() == []
    assert client.get("/customers?include_archived=true").json()[0]["is_active"] is False
    app.dependency_overrides[get_current_user] = lambda: cashier
    assert client.get(f"/customers/{created.json()['id']}").status_code == 404


def test_cashier_cannot_set_manager_owned_customer_fields(customer_client):
    client, _, _, _ = customer_client
    response = client.post(
        "/customers",
        json={"full_name": "Limit Attempt", "credit_limit": "500.00"},
    )
    assert response.status_code == 422


def test_customer_active_status_cannot_be_cleared(customer_client):
    client, _, manager, _ = customer_client
    app.dependency_overrides[get_current_user] = lambda: manager
    created = client.post("/customers", json={"full_name": "Status Test"})
    assert created.status_code == 201

    response = client.patch(
        f"/customers/{created.json()['id']}",
        json={"is_active": None},
    )
    assert response.status_code == 422
