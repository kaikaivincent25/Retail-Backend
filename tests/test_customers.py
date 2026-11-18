from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.api.deps import get_current_user
from app.main import app
from app.models import Customer, CustomerActivity, Shop, User, UserRole


@pytest.fixture
def customer_client() -> Generator[tuple[TestClient, User, User, int, int, sessionmaker], None, None]:
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
        other_cashier = User(
            shop_id=other_shop.id,
            full_name="Other Shop Cashier",
            username="other_customer_shop_cashier",
            password_hash="unused",
            role=UserRole.CASHIER,
        )
        other_customer = Customer(shop_id=other_shop.id, full_name="Private Customer")
        db.add_all([cashier, manager, other_cashier, other_customer])
        db.commit()
        db.refresh(cashier)
        db.refresh(manager)
        db.refresh(other_cashier)
        other_customer_id = other_customer.id
        other_cashier_id = other_cashier.id

    active_user = {"user": cashier}

    def override_db() -> Generator[Session, None, None]:
        with test_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: active_user["user"]
    try:
        yield TestClient(app), cashier, manager, other_customer_id, other_cashier_id, test_session
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_customers_are_shop_scoped_and_limits_are_manager_only(customer_client):
    client, cashier, manager, other_customer_id, _, _ = customer_client
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
    client, _, _, _, _, _ = customer_client
    response = client.post(
        "/customers",
        json={"full_name": "Limit Attempt", "credit_limit": "500.00"},
    )
    assert response.status_code == 422


def test_customer_active_status_cannot_be_cleared(customer_client):
    client, _, manager, _, _, _ = customer_client
    app.dependency_overrides[get_current_user] = lambda: manager
    created = client.post("/customers", json={"full_name": "Status Test"})
    assert created.status_code == 201

    response = client.patch(
        f"/customers/{created.json()['id']}",
        json={"is_active": None},
    )
    assert response.status_code == 422


def test_customer_timeline_records_followups_notes_and_lead_stage(customer_client):
    client, cashier, manager, other_customer_id, _, _ = customer_client
    created = client.post("/customers", json={"full_name": "CRM Customer", "phone": "0712345678"})
    assert created.status_code == 201
    customer_id = created.json()["id"]

    follow_up = client.post(
        f"/customers/{customer_id}/activities",
        json={
            "activity_type": "follow_up",
            "body": "Check if the customer needs more stock",
            "due_at": "2026-12-01T10:00:00+03:00",
        },
    )
    assert follow_up.status_code == 201, follow_up.text
    assert follow_up.json()["status"] == "open"
    assert follow_up.json()["assigned_to_user_id"] == cashier.id

    completed = client.patch(
        f"/customers/{customer_id}/activities/{follow_up.json()['id']}",
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["completed_at"] is not None

    note = client.post(
        f"/customers/{customer_id}/activities",
        json={"activity_type": "note", "body": "Prefers weekday deliveries"},
    )
    assert note.status_code == 201, note.text

    assert client.patch(f"/customers/{customer_id}", json={"lead_status": "contacted"}).status_code == 403
    app.dependency_overrides[get_current_user] = lambda: manager
    stage_update = client.patch(f"/customers/{customer_id}", json={"lead_status": "interested"})
    assert stage_update.status_code == 200
    assert stage_update.json()["lead_status"] == "interested"

    timeline = client.get(f"/customers/{customer_id}/timeline")
    assert timeline.status_code == 200
    entries = timeline.json()["entries"]
    assert {entry["kind"] for entry in entries} >= {"follow_up", "note", "lead_status"}
    assert client.get(f"/customers/{other_customer_id}/timeline").status_code == 404


def test_customer_follow_up_requires_due_date(customer_client):
    client, _, _, _, _, _ = customer_client
    created = client.post("/customers", json={"full_name": "Due Date Customer"})
    response = client.post(
        f"/customers/{created.json()['id']}/activities",
        json={"activity_type": "follow_up", "body": "Call back"},
    )
    assert response.status_code == 422


def test_follow_up_queue_is_shop_scoped_and_managers_can_reassign(customer_client):
    client, cashier, manager, other_customer_id, other_cashier_id, test_session = customer_client
    created = client.post("/customers", json={"full_name": "Queue Customer"})
    assert created.status_code == 201
    follow_up = client.post(
        f"/customers/{created.json()['id']}/activities",
        json={
            "activity_type": "follow_up",
            "body": "Call about the next order",
            "due_at": "2026-12-01T10:00:00+03:00",
        },
    )
    assert follow_up.status_code == 201, follow_up.text

    with test_session() as db:
        other_customer = db.get(Customer, other_customer_id)
        db.add(
            CustomerActivity(
                shop_id=other_customer.shop_id,
                customer_id=other_customer.id,
                activity_type="follow_up",
                body="Other shop follow-up",
                status="open",
                due_at=datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc),
                created_by_user_id=other_cashier_id,
                assigned_to_user_id=other_cashier_id,
            )
        )
        db.commit()

    queue = client.get("/customers/follow-ups")
    assert queue.status_code == 200
    assert [item["customer"]["id"] for item in queue.json()] == [created.json()["id"]]
    assert {staff["id"] for staff in client.get("/customers/follow-ups/assignees").json()} == {
        cashier.id,
        manager.id,
    }

    assignment_response = client.patch(
        f"/customers/{created.json()['id']}/activities/{follow_up.json()['id']}",
        json={"assigned_to_user_id": manager.id},
    )
    assert assignment_response.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: manager
    assignment_response = client.patch(
        f"/customers/{created.json()['id']}/activities/{follow_up.json()['id']}",
        json={"assigned_to_user_id": manager.id},
    )
    assert assignment_response.status_code == 200, assignment_response.text
    assert assignment_response.json()["assigned_to_user_id"] == manager.id
    assert len(client.get(f"/customers/follow-ups?assigned_to_user_id={manager.id}").json()) == 1
    assert client.get(
        f"/customers/follow-ups?assigned_to_user_id={other_cashier_id}"
    ).status_code == 404
