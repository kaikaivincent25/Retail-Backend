from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user_for_billing
from app.core.database import Base, get_db
from app.main import app
from app.models.billing import (
    BillingPaymentStatus,
    BillingPlan,
    Subscription,
    SubscriptionStatus,
)
from app.models.shop import Shop
from app.models.user import User, UserRole


@pytest.fixture
def billing_client() -> Generator[tuple[TestClient, sessionmaker[Session], User], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with test_session() as db:
        shop = Shop(name="Billing Test Shop")
        db.add(shop)
        db.flush()
        free_plan = BillingPlan(
            code="free",
            name="Free",
            monthly_price=0,
            features={"reports.basic": True},
        )
        business_plan = BillingPlan(
            code="business",
            name="Business",
            monthly_price=999,
            features={"online_store": True, "reports.full": True},
        )
        starter_plan = BillingPlan(
            code="starter",
            name="Starter",
            monthly_price=499,
            features={"expenses": True},
        )
        db.add_all([free_plan, business_plan, starter_plan])
        db.flush()
        now = datetime.now(timezone.utc)
        subscription = Subscription(
            shop_id=shop.id,
            plan_id=free_plan.id,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=now + timedelta(days=365),
        )
        user = User(
            shop_id=shop.id,
            full_name="Billing Admin",
            username="billing_test_admin",
            password_hash="unused",
            role=UserRole.ADMIN,
        )
        db.add_all([subscription, user])
        db.commit()
        db.refresh(user)

    def override_db() -> Generator[Session, None, None]:
        with test_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user_for_billing] = lambda: user
    try:
        yield TestClient(app), test_session, user
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_for_billing, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_trial_can_be_canceled_and_resumed_without_unlocking_checkout(billing_client):
    client, _, _ = billing_client
    started = client.post("/billing/start-trial")
    assert started.status_code == 200, started.text
    original_end = started.json()["trial_ends_at"]

    canceled = client.post("/billing/cancel")
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "trialing"
    assert canceled.json()["canceled_at"] is not None
    assert canceled.json()["trial_ends_at"] == original_end

    checkout = client.post(
        "/billing/mpesa/checkout",
        json={"plan_code": "starter", "phone_number": "0712345678"},
    )
    assert checkout.status_code == 409

    resumed = client.post("/billing/resume-trial")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["canceled_at"] is None
    assert resumed.json()["trial_ends_at"] == original_end


def test_checkout_becomes_available_only_after_trial_expiry(billing_client, monkeypatch):
    client, test_session, user = billing_client
    started = client.post("/billing/start-trial")
    assert started.status_code == 200, started.text

    with test_session() as db:
        subscription = db.scalar(select(Subscription).where(Subscription.shop_id == user.shop_id))
        subscription.trial_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        subscription.current_period_end = subscription.trial_ends_at
        db.commit()

    def fake_checkout(db, *, shop_id, user_id, plan, phone_number):
        return SimpleNamespace(
            id=1,
            phone_number=phone_number,
            status=BillingPaymentStatus.PENDING,
        )

    monkeypatch.setattr("app.api.routes.billing.create_billing_payment", fake_checkout)
    checkout = client.post(
        "/billing/mpesa/checkout",
        json={"plan_code": "business", "phone_number": "0712345678"},
    )

    assert checkout.status_code == 202, checkout.text
