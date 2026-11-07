from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    Account,
    Expense,
    JournalEntry,
    JournalLine,
    MovementType,
    PaymentMethod,
    Sale,
    SaleItem,
    SaleStatus,
    Shop,
    StockLot,
    StockLotAllocation,
    StockMovement,
    User,
    UserRole,
)
from app.services.accounting import (
    AccountingError,
    _create_or_verify_entry,
    ensure_default_chart,
    post_completed_sale,
    post_expense,
)


@pytest.fixture
def accounting_db() -> Generator[tuple[Session, Shop, User], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    shop = Shop(name="Accounting Test Shop")
    db.add(shop)
    db.flush()
    user = User(
        shop_id=shop.id,
        full_name="Accounting User",
        username="accounting_test_user",
        password_hash="unused",
        role=UserRole.MANAGER,
    )
    db.add(user)
    db.commit()
    try:
        yield db, shop, user
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _allocate_sale_item_cost(db: Session, sale_item: SaleItem, user: User, lots):
    movement = StockMovement(
        variant_id=1,
        movement_type=MovementType.SALE,
        quantity=-sale_item.quantity,
        previous_quantity=sale_item.quantity,
        new_quantity=0,
        user_id=user.id,
    )
    db.add(movement)
    db.flush()
    for quantity, unit_cost in lots:
        lot = StockLot(
            variant_id=1,
            received_quantity=quantity,
            remaining_quantity=0,
            unit_cost=unit_cost,
        )
        db.add(lot)
        db.flush()
        db.add(
            StockLotAllocation(
                lot_id=lot.id,
                stock_movement_id=movement.id,
                sale_item_id=sale_item.id,
                quantity=quantity,
                unit_cost=unit_cost,
            )
        )
    db.flush()


def test_default_chart_is_shop_scoped_and_repeatable(accounting_db):
    db, shop, _ = accounting_db
    accounts = ensure_default_chart(db, shop.id)
    db.commit()
    assert len(accounts) == 13
    assert len(
        db.scalars(select(Account).where(Account.shop_id == shop.id)).all()
    ) == 13

    again = ensure_default_chart(db, shop.id)
    assert len(again) == 13

    other_shop = Shop(name="Separate Accounting Shop")
    db.add(other_shop)
    db.flush()
    other_accounts = ensure_default_chart(db, other_shop.id)
    assert len(other_accounts) == 13
    assert {account.id for account in accounts.values()}.isdisjoint(
        account.id for account in other_accounts.values()
    )


@pytest.mark.parametrize(
    ("payment_method", "cash_account"),
    [
        (PaymentMethod.CASH, "1000"),
        (PaymentMethod.MPESA, "1010"),
        (PaymentMethod.POCHI, "1010"),
        (PaymentMethod.TILL, "1010"),
        (PaymentMethod.PAYBILL, "1010"),
    ],
)
def test_completed_sale_posts_balanced_idempotent_entry(
    accounting_db, payment_method, cash_account
):
    db, shop, user = accounting_db
    sale = Sale(
        shop_id=shop.id,
        cashier_id=user.id,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        amount_received=Decimal("100.00"),
        change=Decimal("0.00"),
        payment_method=payment_method,
        status=SaleStatus.COMPLETED,
    )
    db.add(sale)
    db.flush()
    sale.items.append(
        SaleItem(
            variant_id=1,
            variant_name="Test item",
            quantity=2,
            unit_price=Decimal("50.00"),
            unit_cost_at_sale=Decimal("30.00"),
            cost_is_known_at_sale=True,
            line_total=Decimal("100.00"),
        )
    )
    db.flush()
    _allocate_sale_item_cost(
        db, sale.items[0], user, [(2, Decimal("30.00"))]
    )

    entry = post_completed_sale(db, sale)
    db.commit()
    assert sum((line.debit for line in entry.lines), Decimal("0.00")) == Decimal("160.00")
    assert sum((line.credit for line in entry.lines), Decimal("0.00")) == Decimal("160.00")
    assert {(line.account.code, line.debit, line.credit) for line in entry.lines} == {
        (cash_account, Decimal("100.00"), Decimal("0.00")),
        ("4000", Decimal("0.00"), Decimal("100.00")),
        ("5000", Decimal("60.00"), Decimal("0.00")),
        ("1100", Decimal("0.00"), Decimal("60.00")),
    }
    assert entry.currency == shop.currency

    duplicate = post_completed_sale(db, sale)
    assert duplicate.id == entry.id
    assert db.scalar(select(func.count(JournalEntry.id))) == 1


def test_sale_cogs_uses_unrounded_fifo_allocation_total(accounting_db):
    db, shop, user = accounting_db
    sale = Sale(
        shop_id=shop.id,
        cashier_id=user.id,
        subtotal=Decimal("150.00"),
        total=Decimal("150.00"),
        amount_received=Decimal("150.00"),
        change=Decimal("0.00"),
        payment_method=PaymentMethod.CASH,
        status=SaleStatus.COMPLETED,
    )
    db.add(sale)
    db.flush()
    sale.items.append(
        SaleItem(
            variant_id=1,
            variant_name="Test item",
            quantity=3,
            unit_price=Decimal("50.00"),
            unit_cost_at_sale=Decimal("10.01"),
            cost_is_known_at_sale=True,
            line_total=Decimal("150.00"),
        )
    )
    db.flush()
    _allocate_sale_item_cost(
        db,
        sale.items[0],
        user,
        [(1, Decimal("10.00")), (2, Decimal("10.01"))],
    )

    entry = post_completed_sale(db, sale)
    assert sum(
        (line.debit for line in entry.lines if line.account.code == "5000"),
        Decimal("0.00"),
    ) == Decimal("30.02")


@pytest.mark.parametrize(
    ("funding_source", "credit_account"),
    [("cash", "1000"), ("bank", "1020")],
)
def test_expense_posts_to_expense_and_correct_funding_account(
    accounting_db, funding_source, credit_account
):
    db, shop, user = accounting_db
    expense = Expense(
        user_id=user.id,
        category="Transport",
        description="Delivery",
        amount=Decimal("25.50"),
        funding_source=funding_source,
    )
    db.add(expense)
    db.flush()

    entry = post_expense(db, expense, shop.id)
    db.commit()
    assert {(line.account.code, line.debit, line.credit) for line in entry.lines} == {
        ("5100", Decimal("25.50"), Decimal("0.00")),
        (credit_account, Decimal("0.00"), Decimal("25.50")),
    }


def test_noncompleted_sale_cannot_be_posted(accounting_db):
    db, shop, user = accounting_db
    sale = Sale(
        shop_id=shop.id,
        cashier_id=user.id,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        amount_received=Decimal("100.00"),
        change=Decimal("0.00"),
        payment_method=PaymentMethod.CASH,
        status=SaleStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
    )
    db.add(sale)
    db.flush()
    sale.items.append(
        SaleItem(
            variant_id=1,
            variant_name="Test item",
            quantity=1,
            unit_price=Decimal("100.00"),
            unit_cost_at_sale=Decimal("20.00"),
            cost_is_known_at_sale=True,
            line_total=Decimal("100.00"),
        )
    )
    db.flush()
    sale.status = SaleStatus.PENDING
    with pytest.raises(AccountingError, match="Only completed"):
        post_completed_sale(db, sale)


def test_unbalanced_journal_is_rejected(accounting_db):
    db, shop, user = accounting_db
    with pytest.raises(AccountingError, match="debits and credits must be equal"):
        _create_or_verify_entry(
            db,
            shop_id=shop.id,
            entry_date=datetime.now(timezone.utc).date(),
            source_type="test",
            source_id=1,
            description="Invalid journal",
            created_by_user_id=user.id,
            lines=[
                ("1000", Decimal("10.00"), Decimal("0.00"), "Cash"),
                ("4000", Decimal("0.00"), Decimal("9.00"), "Revenue"),
            ],
        )


def test_accounting_api_is_manager_only_and_shop_scoped(accounting_db):
    db, shop, manager = accounting_db
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: manager
    try:
        client = TestClient(app)
        accounts = client.get("/accounting/accounts")
        assert accounts.status_code == 200
        assert len(accounts.json()) == 13
        assert client.get("/accounting/journal").json() == []

        expense = Expense(
            user_id=manager.id,
            category="Utilities",
            amount=Decimal("10.00"),
            funding_source="bank",
        )
        db.add(expense)
        db.flush()
        post_expense(db, expense, shop.id)
        db.commit()
        journal = client.get("/accounting/journal")
        assert journal.status_code == 200
        assert len(journal.json()) == 1
        assert journal.json()[0]["currency"] == shop.currency
        assert journal.json()[0]["debit_total"] == "10.00"
        assert journal.json()[0]["credit_total"] == "10.00"

        manager.role = UserRole.ADMIN
        db.commit()
        currency_change = client.patch("/shop", json={"currency": "USD"})
        assert currency_change.status_code == 409

        cashier = User(
            shop_id=shop.id,
            full_name="Accounting Cashier",
            username="accounting_test_cashier",
            password_hash="unused",
            role=UserRole.CASHIER,
        )
        db.add(cashier)
        db.commit()
        app.dependency_overrides[get_current_user] = lambda: cashier
        assert client.get("/accounting/accounts").status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
