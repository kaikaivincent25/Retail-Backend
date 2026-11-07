from collections.abc import Generator
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    CashSession,
    Customer,
    CustomerPayment,
    JournalEntry,
    MovementType,
    PaymentMethod,
    Product,
    Sale,
    SaleItem,
    SaleStatus,
    SessionStatus,
    Shop,
    StockLot,
    StockLotAllocation,
    StockMovement,
    User,
    UserRole,
    Unit,
    Variant,
)
from app.services.accounting import (
    AccountingError,
    ensure_default_chart,
    post_completed_sale,
    post_customer_payment,
)
from app.services.cash_sessions import close_session, open_session
from app.services.customer_payments import (
    CustomerPaymentError,
    calculate_customer_outstanding,
    get_customer_ledger,
    record_customer_payment,
)
from app.services.sales import complete_sale


@pytest.fixture
def test_setup() -> Generator[tuple[Session, Shop, User, User, Customer], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()

    shop = Shop(name="Credit Accounting Test Shop", currency="KES")
    db.add(shop)
    db.flush()

    manager = User(
        shop_id=shop.id,
        full_name="Test Manager",
        username="credit_mgr",
        password_hash="unused",
        role=UserRole.MANAGER,
    )
    cashier = User(
        shop_id=shop.id,
        full_name="Test Cashier",
        username="credit_cshr",
        password_hash="unused",
        role=UserRole.CASHIER,
    )
    customer = Customer(
        shop_id=shop.id,
        full_name="Credited Customer",
        phone="0711223344",
        credit_limit=Decimal("5000.00"),
        is_active=True,
    )
    db.add_all([manager, cashier, customer])
    db.commit()

    try:
        yield db, shop, manager, cashier, customer
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _setup_product_and_lot(db: Session, shop_id: int, user_id: int, price: Decimal, cost: Decimal, qty: int = 100):
    product = Product(shop_id=shop_id, name="Test Product")
    db.add(product)
    db.flush()
    variant = Variant(
        product_id=product.id,
        name="Standard",
        unit=Unit.PIECE,
        selling_price=price,
        cost_price=cost,
        cost_price_is_known=True,
        quantity=qty,
        is_active=True,
    )
    db.add(variant)
    db.flush()
    lot = StockLot(
        variant_id=variant.id,
        received_quantity=qty,
        remaining_quantity=qty,
        unit_cost=cost,
    )
    db.add(lot)
    db.commit()
    return variant


def test_credit_sale_requires_due_date_and_active_customer(test_setup):
    db, shop, manager, cashier, customer = test_setup
    variant = _setup_product_and_lot(db, shop.id, cashier.id, Decimal("100.00"), Decimal("60.00"))

    # Missing due date
    with pytest.raises(Exception) as exc:
        complete_sale(
            db,
            shop_id=shop.id,
            cashier_id=cashier.id,
            items=[{"variant_id": variant.id, "quantity": 1}],
            amount_received=Decimal("0.00"),
            payment_method=PaymentMethod.CASH,
            customer_id=customer.id,
            is_credit=True,
            due_date=None,
        )
    assert "due date" in str(exc.value).lower()

    # Due date in the past
    with pytest.raises(Exception) as exc:
        complete_sale(
            db,
            shop_id=shop.id,
            cashier_id=cashier.id,
            items=[{"variant_id": variant.id, "quantity": 1}],
            amount_received=Decimal("0.00"),
            payment_method=PaymentMethod.CASH,
            customer_id=customer.id,
            is_credit=True,
            due_date=date.today() - timedelta(days=1),
        )
    assert "past" in str(exc.value).lower()

    # Archived/inactive customer
    customer.is_active = False
    db.commit()
    with pytest.raises(Exception) as exc:
        complete_sale(
            db,
            shop_id=shop.id,
            cashier_id=cashier.id,
            items=[{"variant_id": variant.id, "quantity": 1}],
            amount_received=Decimal("0.00"),
            payment_method=PaymentMethod.CASH,
            customer_id=customer.id,
            is_credit=True,
            due_date=date.today() + timedelta(days=14),
        )
    assert "inactive" in str(exc.value).lower()


def test_credit_sale_limit_enforced(test_setup):
    db, shop, manager, cashier, customer = test_setup
    # Customer credit limit is 5000. Price is 3000 each.
    variant = _setup_product_and_lot(db, shop.id, cashier.id, Decimal("3000.00"), Decimal("1500.00"))

    # 1st purchase of 3000 succeeds
    sale1 = complete_sale(
        db,
        shop_id=shop.id,
        cashier_id=cashier.id,
        items=[{"variant_id": variant.id, "quantity": 1}],
        amount_received=Decimal("0.00"),
        customer_id=customer.id,
        is_credit=True,
        due_date=date.today() + timedelta(days=7),
    )
    assert sale1.total == Decimal("3000.00")
    assert sale1.is_credit is True

    # 2nd purchase of 3000 would bring outstanding to 6000 > 5000 -> must fail
    with pytest.raises(Exception) as exc:
        complete_sale(
            db,
            shop_id=shop.id,
            cashier_id=cashier.id,
            items=[{"variant_id": variant.id, "quantity": 1}],
            amount_received=Decimal("0.00"),
            customer_id=customer.id,
            is_credit=True,
            due_date=date.today() + timedelta(days=7),
        )
    assert "credit limit" in str(exc.value).lower()


def test_credit_sale_posts_balanced_journal_and_does_not_affect_till_cash(test_setup):
    db, shop, manager, cashier, customer = test_setup
    variant = _setup_product_and_lot(db, shop.id, cashier.id, Decimal("1000.00"), Decimal("600.00"))

    # Open a cash session with 500 opening cash
    session = open_session(db, user_id=cashier.id, shop_id=shop.id)
    assert session.opening_cash == Decimal("0.00")

    # Complete a credit sale of 1000 with no down payment
    due = date.today() + timedelta(days=30)
    sale = complete_sale(
        db,
        shop_id=shop.id,
        cashier_id=cashier.id,
        items=[{"variant_id": variant.id, "quantity": 1}],
        amount_received=Decimal("0.00"),
        session_id=session.id,
        customer_id=customer.id,
        is_credit=True,
        due_date=due,
    )
    assert sale.total == Decimal("1000.00")
    assert sale.is_credit is True
    assert sale.due_date == due

    # Verify journal entry was posted and balances
    entry = db.scalar(
        select(JournalEntry).where(
            JournalEntry.shop_id == shop.id,
            JournalEntry.source_type == "sale",
            JournalEntry.source_id == sale.id,
        )
    )
    assert entry is not None
    debits = sum((line.debit for line in entry.lines), Decimal("0.00"))
    credits = sum((line.credit for line in entry.lines), Decimal("0.00"))
    assert debits == credits == Decimal("1600.00")  # 1000 AR + 600 COGS = 1000 Revenue + 600 Inventory

    lines_map = {(line.account.code, line.debit, line.credit) for line in entry.lines}
    assert ("1200", Decimal("1000.00"), Decimal("0.00")) in lines_map  # AR debited
    assert ("4000", Decimal("0.00"), Decimal("1000.00")) in lines_map  # Revenue credited
    assert ("5000", Decimal("600.00"), Decimal("0.00")) in lines_map   # COGS debited
    assert ("1100", Decimal("0.00"), Decimal("600.00")) in lines_map   # Inventory credited

    # Close session: Expected cash must NOT include the credit sale!
    # Expected cash = opening cash (0) = 0.
    closed = close_session(db, session, closing_cash=Decimal("0.00"), closed_by_user_id=cashier.id)
    assert closed.expected_cash == Decimal("0.00")
    assert closed.closing_cash == Decimal("0.00")


def test_credit_sale_with_initial_payment_and_repayment(test_setup):
    db, shop, manager, cashier, customer = test_setup
    variant = _setup_product_and_lot(db, shop.id, cashier.id, Decimal("1000.00"), Decimal("600.00"))

    session = open_session(db, user_id=cashier.id, shop_id=shop.id)

    # 1. Credit sale with 200 cash down payment
    due = date.today() + timedelta(days=14)
    sale = complete_sale(
        db,
        shop_id=shop.id,
        cashier_id=cashier.id,
        items=[{"variant_id": variant.id, "quantity": 1}],
        amount_received=Decimal("200.00"),
        session_id=session.id,
        customer_id=customer.id,
        is_credit=True,
        due_date=due,
        initial_payment=Decimal("200.00"),
        initial_payment_method=PaymentMethod.CASH,
    )

    # Down payment recorded as CustomerPayment
    initial_payment = db.scalar(
        select(CustomerPayment).where(
            CustomerPayment.sale_id == sale.id,
            CustomerPayment.customer_id == customer.id,
        )
    )
    assert initial_payment is not None
    assert initial_payment.amount == Decimal("200.00")
    assert initial_payment.payment_method == PaymentMethod.CASH
    assert initial_payment.session_id == session.id

    # Outstanding balance should now be 800
    outstanding, overdue = calculate_customer_outstanding(db, shop.id, customer.id)
    assert outstanding == Decimal("800.00")
    assert overdue == Decimal("0.00")

    # 2. Record subsequent partial repayment of 300 via cash
    repayment1 = record_customer_payment(
        db,
        shop_id=shop.id,
        user_id=cashier.id,
        customer_id=customer.id,
        sale_id=sale.id,
        amount=Decimal("300.00"),
        payment_method=PaymentMethod.CASH,
        reference="Receipt #123",
        session_id=session.id,
    )
    assert repayment1.amount == Decimal("300.00")

    # Outstanding is now 500
    outstanding, _ = calculate_customer_outstanding(db, shop.id, customer.id)
    assert outstanding == Decimal("500.00")

    # 3. Attempt overpayment of 600 > 500 -> must fail
    with pytest.raises(CustomerPaymentError) as exc:
        record_customer_payment(
            db,
            shop_id=shop.id,
            user_id=cashier.id,
            customer_id=customer.id,
            sale_id=sale.id,
            amount=Decimal("600.00"),
            payment_method=PaymentMethod.CASH,
        )
    assert "exceeds remaining balance" in str(exc.value).lower()

    # 4. Pay remaining 500 via M-Pesa
    repayment2 = record_customer_payment(
        db,
        shop_id=shop.id,
        user_id=cashier.id,
        customer_id=customer.id,
        sale_id=sale.id,
        amount=Decimal("500.00"),
        payment_method=PaymentMethod.MPESA,
        reference="QKX12345",
    )
    assert repayment2.amount == Decimal("500.00")

    # Outstanding is now 0
    outstanding, _ = calculate_customer_outstanding(db, shop.id, customer.id)
    assert outstanding == Decimal("0.00")

    # 5. Verify journal entries for repayments
    pay_entry = db.scalar(
        select(JournalEntry).where(
            JournalEntry.shop_id == shop.id,
            JournalEntry.source_type == "customer_payment",
            JournalEntry.source_id == repayment2.id,
        )
    )
    assert pay_entry is not None
    p_lines = {(line.account.code, line.debit, line.credit) for line in pay_entry.lines}
    assert ("1010", Decimal("500.00"), Decimal("0.00")) in p_lines  # M-Pesa debited
    assert ("1200", Decimal("0.00"), Decimal("500.00")) in p_lines  # AR credited

    # 6. Verify cash session expected cash
    # Initial payment 200 cash + partial payment 300 cash = 500 cash received
    # (The 500 M-Pesa payment does NOT count towards till cash)
    closed = close_session(db, session, closing_cash=Decimal("500.00"), closed_by_user_id=cashier.id)
    assert closed.expected_cash == Decimal("500.00")
    assert closed.difference == Decimal("0.00")


def test_customer_ledger_and_accounting_endpoints(test_setup):
    db, shop, manager, cashier, customer = test_setup
    variant = _setup_product_and_lot(db, shop.id, cashier.id, Decimal("1000.00"), Decimal("500.00"))

    # Create credit sale with due date in the past to test overdue aging
    past_due = date.today() - timedelta(days=10)
    sale = Sale(
        shop_id=shop.id,
        cashier_id=cashier.id,
        customer_id=customer.id,
        is_credit=True,
        due_date=past_due,
        subtotal=Decimal("1000.00"),
        total=Decimal("1000.00"),
        amount_received=Decimal("0.00"),
        change=Decimal("0.00"),
        payment_method=PaymentMethod.CASH,
        status=SaleStatus.COMPLETED,
    )
    db.add(sale)
    db.flush()
    sale.items.append(
        SaleItem(
            variant_id=variant.id,
            variant_name=variant.name,
            quantity=1,
            unit_price=Decimal("1000.00"),
            unit_cost_at_sale=Decimal("500.00"),
            cost_is_known_at_sale=True,
            line_total=Decimal("1000.00"),
        )
    )
    db.flush()
    db.add(
        StockLotAllocation(
            lot_id=1,
            stock_movement_id=1,
            sale_item_id=sale.items[0].id,
            quantity=1,
            unit_cost=Decimal("500.00"),
        )
    )
    post_completed_sale(db, sale)
    db.commit()

    # Test customer ledger
    ledger = get_customer_ledger(db, shop.id, customer.id)
    assert ledger["total_credit_sales"] == Decimal("1000.00")
    assert ledger["outstanding_balance"] == Decimal("1000.00")
    assert ledger["overdue_balance"] == Decimal("1000.00")
    assert len(ledger["invoices"]) == 1
    assert ledger["invoices"][0]["status"] == "overdue"

    # Test client endpoints
    active_user = {"user": manager}
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: active_user["user"]
    client = TestClient(app)

    try:
        # Receivables endpoint
        r_res = client.get("/accounting/receivables")
        assert r_res.status_code == 200
        r_data = r_res.json()
        assert r_data["total_outstanding"] == "1000.00"
        assert r_data["total_overdue"] == "1000.00"
        assert r_data["overdue_1_30"] == "1000.00"
        assert len(r_data["customers"]) == 1

        # Performance endpoint
        p_res = client.get(f"/accounting/performance?start_date={past_due}&end_date={date.today()}")
        assert p_res.status_code == 200
        p_data = p_res.json()
        assert p_data["basis"] == "accrual"
        assert p_data["sales_revenue"] == "1000.00"
        assert p_data["cost_of_goods_sold"] == "500.00"
        assert p_data["gross_profit"] == "500.00"

        # Reconciliation endpoint
        rec_res = client.get(f"/accounting/reconciliation?start_date={past_due}&end_date={date.today()}")
        assert rec_res.status_code == 200
        rec_data = rec_res.json()
        assert rec_data["sales_credit"] == "1000.00"
        assert rec_data["receivables_issued"] == "1000.00"

        # Cashier role-gating: cashier cannot access accounting endpoints
        active_user["user"] = cashier
        assert client.get("/accounting/receivables").status_code == 403
        assert client.get("/accounting/performance").status_code == 403
        assert client.get("/accounting/reconciliation").status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
