from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.ai import build_shop_context
from app.core.database import Base
from app.models import (
    CashSession,
    Expense,
    PaymentMethod,
    Product,
    Sale,
    SaleItem,
    SaleStatus,
    SessionStatus,
    Shop,
    Unit,
    User,
    UserRole,
    Variant,
)


@pytest.fixture
def assistant_db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_shop_context_includes_catalog_sales_expenses_and_cash_session(assistant_db):
    db = assistant_db
    shop = Shop(name="Assistant Test Shop", business_type="grocery", currency="KES")
    db.add(shop)
    db.flush()
    cashier = User(
        shop_id=shop.id,
        full_name="Test Cashier",
        username="assistant_test_cashier",
        password_hash="unused",
        role=UserRole.CASHIER,
    )
    db.add(cashier)
    db.flush()
    product = Product(
        shop_id=shop.id,
        name="Tea",
        category="Beverages",
        is_active=True,
    )
    db.add(product)
    db.flush()
    variant = Variant(
        product_id=product.id,
        name="500 g",
        unit=Unit.PACKET,
        selling_price=Decimal("50.00"),
        quantity=4,
        reorder_level=2,
    )
    db.add(variant)
    db.flush()
    cash_session = CashSession(
        shop_id=shop.id,
        user_id=cashier.id,
        opening_cash=Decimal("100.00"),
        cash_sales_total=Decimal("100.00"),
        cash_collections_total=Decimal("0.00"),
        cash_expenses_total=Decimal("25.00"),
        expected_cash=Decimal("175.00"),
        status=SessionStatus.OPEN,
    )
    db.add(cash_session)
    db.flush()
    sale = Sale(
        shop_id=shop.id,
        cashier_id=cashier.id,
        session_id=cash_session.id,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        amount_received=Decimal("100.00"),
        change=Decimal("0.00"),
        payment_method=PaymentMethod.CASH,
        status=SaleStatus.COMPLETED,
    )
    db.add(sale)
    db.flush()
    db.add(
        SaleItem(
            sale_id=sale.id,
            variant_id=variant.id,
            variant_name=variant.name,
            quantity=2,
            unit_price=Decimal("50.00"),
            unit_cost_at_sale=Decimal("30.00"),
            cost_is_known_at_sale=True,
            line_total=Decimal("100.00"),
        )
    )
    db.add(
        Expense(
            user_id=cashier.id,
            session_id=cash_session.id,
            category="supplies",
            amount=Decimal("25.00"),
            funding_source="cash",
        )
    )
    db.commit()

    context = build_shop_context(db, shop.id)

    assert context["shop_profile"] == {
        "name": "Assistant Test Shop",
        "business_type": "grocery",
        "currency": "KES",
    }
    assert context["catalog"] == {
        "active_products": 1,
        "active_variants": 1,
        "units_in_stock": 4,
        "categories_in_use": 1,
        "active_customers": 0,
    }
    assert context["sales"]["revenue"] == 100.0
    assert context["sales_by_payment_method"]["cash"]["transaction_count"] == 1
    assert context["expenses_last_30_days_by_category"] == {"supplies": 25.0}
    assert context["open_cash_session"]["expected_cash"] == 175.0
