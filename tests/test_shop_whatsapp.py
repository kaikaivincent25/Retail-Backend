from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, require_platform_owner
from app.core.database import Base, get_db
from app.main import app
from app.models import Shop, User, UserRole
from app.models.billing import BillingPlan, Subscription, SubscriptionStatus
from app.models.platform import PlatformAuditLog, PlatformUser


@pytest.fixture
def whatsapp_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    shop = Shop(name="WhatsApp Shop", slug="whatsapp-shop")
    other_shop = Shop(name="Other WhatsApp Shop", slug="other-whatsapp-shop")
    db.add_all([shop, other_shop])
    db.flush()
    plan = BillingPlan(code="business", name="Business", monthly_price=999, features={"online_store": True})
    free_plan = BillingPlan(code="free", name="Free", monthly_price=0, annual_price=0, features={})
    db.add_all([plan, free_plan])
    db.flush()
    now = datetime.now(timezone.utc)
    db.add_all([
        Subscription(
            shop_id=shop.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        ),
        Subscription(
            shop_id=other_shop.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        ),
    ])
    admin = User(
        shop_id=shop.id,
        full_name="Shop Admin",
        username="whatsapp_admin",
        password_hash="unused",
        role=UserRole.ADMIN,
    )
    other_admin = User(
        shop_id=other_shop.id,
        full_name="Other Admin",
        username="other_whatsapp_admin",
        password_hash="unused",
        role=UserRole.ADMIN,
    )
    cashier = User(
        shop_id=shop.id,
        full_name="Shop Cashier",
        username="whatsapp_cashier",
        password_hash="unused",
        role=UserRole.CASHIER,
    )
    db.add_all([admin, other_admin, cashier])
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        yield TestClient(app), db, shop, other_shop, admin, other_admin, cashier
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def test_admin_can_save_normalized_shop_whatsapp_and_storefront_exposes_it(whatsapp_client):
    client, db, shop, _, _, _, _ = whatsapp_client

    response = client.patch("/shop", json={"whatsapp_number": "0712 345 678"})

    assert response.status_code == 200
    assert response.json()["whatsapp_number"] == "+254712345678"
    assert client.get(f"/public/shops/{shop.slug}").json()["whatsapp_number"] == "+254712345678"
    db.refresh(shop)
    assert shop.whatsapp_number == "+254712345678"


def test_shop_whatsapp_is_scoped_and_can_be_cleared(whatsapp_client):
    client, db, shop, other_shop, _, other_admin, _ = whatsapp_client
    shop.whatsapp_number = "+254701111111"
    other_shop.whatsapp_number = "+254702222222"
    db.commit()

    app.dependency_overrides[get_current_user] = lambda: other_admin
    response = client.patch("/shop", json={"whatsapp_number": ""})

    assert response.status_code == 200
    assert response.json()["whatsapp_number"] is None
    db.refresh(shop)
    db.refresh(other_shop)
    assert shop.whatsapp_number == "+254701111111"
    assert other_shop.whatsapp_number is None


def test_platform_owner_can_suspend_storefront_without_suspending_subscription(whatsapp_client):
    client, db, shop, _, _, _, _ = whatsapp_client
    platform_user = PlatformUser(
        full_name="Platform Owner",
        username="platform_feature_admin",
        password_hash="unused",
    )
    db.add(platform_user)
    db.commit()
    app.dependency_overrides[require_platform_owner] = lambda: platform_user
    try:
        shops_response = client.get("/platform/shops")
        assert shops_response.status_code == 200, shops_response.text
        assert shops_response.json()[0]["features"]["online_store"] is True

        response = client.patch(
            f"/platform/shops/{shop.id}/features",
            json={"suspended_features": ["online_store"]},
        )

        assert response.status_code == 200, response.text
        assert response.json()["suspended_features"] == ["online_store"]
        assert client.get(f"/public/shops/{shop.slug}").status_code == 402
        assert db.query(PlatformAuditLog).filter_by(action="shop_features_updated").count() == 1
    finally:
        app.dependency_overrides.pop(require_platform_owner, None)


def test_platform_owner_can_edit_plan_prices_limits_and_features(whatsapp_client):
    client, db, *_ = whatsapp_client
    platform_user = PlatformUser(
        full_name="Platform Plan Admin",
        username="platform_plan_admin",
        password_hash="unused",
    )
    db.add(platform_user)
    db.commit()
    app.dependency_overrides[require_platform_owner] = lambda: platform_user
    try:
        plans_response = client.get("/platform/plans")
        assert plans_response.status_code == 200, plans_response.text
        assert any(plan["code"] == "business" for plan in plans_response.json())

        response = client.patch(
            "/platform/plans/business",
            json={
                "monthly_price": 1299,
                "annual_price": 12990,
                "max_users": 18,
                "features": {"online_store": True, "reports.full": True},
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["monthly_price"] == 1299
        assert response.json()["annual_price"] == 12990
        assert response.json()["max_users"] == 18
        assert response.json()["features"]["reports.full"] is True
        assert db.query(PlatformAuditLog).filter_by(action="billing_plan_updated").count() == 1

        free_price_response = client.patch(
            "/platform/plans/free",
            json={"monthly_price": 99, "annual_price": 0, "max_users": 2, "features": {}},
        )
        assert free_price_response.status_code == 422
    finally:
        app.dependency_overrides.pop(require_platform_owner, None)


@pytest.mark.parametrize("number", ["not-a-number", "123", "++254712345678"])
def test_shop_whatsapp_rejects_invalid_numbers(whatsapp_client, number):
    client, *_ = whatsapp_client

    response = client.patch("/shop", json={"whatsapp_number": number})

    assert response.status_code == 422


def test_non_admin_cannot_update_shop_whatsapp(whatsapp_client):
    client, _, _, _, _, _, cashier = whatsapp_client
    app.dependency_overrides[get_current_user] = lambda: cashier

    response = client.patch("/shop", json={"whatsapp_number": "0712345678"})

    assert response.status_code == 403
