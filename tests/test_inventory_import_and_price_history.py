from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    Product,
    Shop,
    StockLot,
    StockMovement,
    User,
    UserRole,
    Variant,
    VariantPriceHistory,
)
from app.models.billing import BillingPlan, Subscription, SubscriptionStatus


@pytest.fixture
def inventory_client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
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
        shop = Shop(name="Inventory Import Test Shop", slug="inventory-import-test")
        db.add(shop)
        db.flush()
        plan = BillingPlan(
            code="business",
            name="Business",
            monthly_price=999,
            features={"inventory.reports": True, "online_store": True},
        )
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
        manager = User(
            shop_id=shop.id,
            full_name="Inventory Manager",
            username="inventory_import_manager",
            password_hash="unused",
            role=UserRole.MANAGER,
        )
        db.add(manager)
        db.commit()

    def override_db() -> Generator[Session, None, None]:
        with test_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: manager
    try:
        yield TestClient(app), test_session
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_import_receives_opening_stock_and_later_receipt_reuses_last_cost(inventory_client):
    client, test_session = inventory_client
    response = client.post(
        "/products/bulk",
        json=[
            {
                "name": "Imported Coffee",
                "variants": [
                    {
                        "name": "500g bag",
                        "unit": "piece",
                        "selling_price": "125.00",
                        "cost_price": "100.00",
                        "initial_quantity": 6,
                    }
                ],
            }
        ],
    )
    assert response.status_code == 201, response.text
    costs_response = client.get("/inventory/costs")
    assert costs_response.status_code == 200, costs_response.text
    assert costs_response.json()[0]["latest_purchase_unit_cost"] == "100.00"
    inventory_response = client.get("/inventory")
    assert inventory_response.status_code == 200, inventory_response.text
    assert inventory_response.json()[0]["selling_price"] == "125.00"

    with test_session() as db:
        variant = db.scalar(
            select(Variant)
            .join(Product)
            .where(Product.name == "Imported Coffee")
        )
        assert variant is not None
        variant_id = variant.id
        assert variant.quantity == 6
        opening_lot = db.scalar(
            select(StockLot).where(StockLot.variant_id == variant.id)
        )
        assert opening_lot is not None
        assert opening_lot.remaining_quantity == 6
        assert str(opening_lot.unit_cost) == "100.00"
        opening_movement = db.scalar(
            select(StockMovement).where(StockMovement.variant_id == variant.id)
        )
        assert opening_movement.reason == "Opening stock from product import"

    movements = client.get(f"/inventory/{variant_id}/movements")
    assert movements.status_code == 200, movements.text
    assert movements.json()[0]["user_name"] == "Inventory Manager"

    receipt = client.post(
        f"/inventory/{variant_id}/adjust",
        json={"delta": 4, "movement_type": "purchase"},
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["quantity"] == 10

    with test_session() as db:
        variant = db.get(Variant, variant_id)
        assert str(variant.cost_price) == "100.00"
        lots = db.scalars(
            select(StockLot)
            .where(StockLot.variant_id == variant_id)
            .order_by(StockLot.id)
        ).all()
        assert len(lots) == 2
        assert all(str(lot.unit_cost) == "100.00" for lot in lots)

    changed_cost_receipt = client.post(
        f"/inventory/{variant_id}/adjust",
        json={"delta": 2, "movement_type": "purchase", "unit_cost": "120.00"},
    )
    assert changed_cost_receipt.status_code == 200, changed_cost_receipt.text
    with test_session() as db:
        variant = db.get(Variant, variant_id)
        assert str(variant.cost_price) == "103.33"
        lots = db.scalars(
            select(StockLot).where(StockLot.variant_id == variant_id)
        ).all()
        assert str(lots[-1].unit_cost) == "120.00"


def test_variant_price_changes_are_attributed_and_history_is_retrievable(inventory_client):
    client, test_session = inventory_client
    response = client.post(
        "/products/bulk",
        json=[
            {
                "name": "Imported Tea",
                "variants": [
                    {
                        "name": "Box",
                        "unit": "box",
                        "selling_price": "150.00",
                        "cost_price": "100.00",
                    }
                ],
            }
        ],
    )
    assert response.status_code == 201, response.text
    with test_session() as db:
        variant = db.scalar(
            select(Variant).join(Product).where(Product.name == "Imported Tea")
        )
        variant_id = variant.id

    update = client.patch(
        f"/variants/{variant_id}",
        json={"selling_price": "160.00"},
    )
    assert update.status_code == 200, update.text

    history = client.get(f"/variants/{variant_id}/price-history")
    assert history.status_code == 200, history.text
    changes = history.json()
    assert len(changes) == 2
    assert changes[0]["old_price"] == "150.00"
    assert changes[0]["new_price"] == "160.00"
    assert changes[0]["changed_by_name"] == "Inventory Manager"
    assert changes[1]["old_price"] is None
    assert changes[1]["new_price"] == "150.00"

    with test_session() as db:
        assert len(
            db.scalars(
                select(VariantPriceHistory).where(
                    VariantPriceHistory.variant_id == variant_id
                )
            ).all()
        ) == 2


def test_variant_image_overrides_product_image_and_can_be_cleared(inventory_client):
    client, _ = inventory_client
    response = client.post(
        "/products",
        json={
            "name": "Image Test Product",
            "image_url": "https://images.example.com/product.jpg",
            "public_image_url": "https://images.example.com/public-product.jpg",
            "is_public": True,
            "variants": [
                {
                    "name": "Blue",
                    "unit": "piece",
                    "selling_price": "10.00",
                    "image_url": "https://images.example.com/blue.jpg",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    product = response.json()
    variant_id = product["variants"][0]["id"]
    assert product["variants"][0]["image_url"] == "https://images.example.com/blue.jpg"

    browsed = client.get("/variants")
    assert browsed.status_code == 200, browsed.text
    assert browsed.json()[0]["image_url"] == "https://images.example.com/blue.jpg"
    public = client.get("/public/shops/inventory-import-test")
    assert public.status_code == 200, public.text
    assert public.json()["products"][0]["variants"][0]["image_url"] == (
        "https://images.example.com/blue.jpg"
    )

    cleared = client.patch(f"/variants/{variant_id}", json={"image_url": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["image_url"] is None
    browsed = client.get("/variants")
    assert browsed.json()[0]["image_url"] == "https://images.example.com/product.jpg"
    public = client.get("/public/shops/inventory-import-test")
    assert public.json()["products"][0]["variants"][0]["image_url"] == (
        "https://images.example.com/public-product.jpg"
    )
