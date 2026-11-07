from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.accounting import Account, AccountType, JournalEntry, JournalLine
from app.models.customer_payment import CustomerPayment
from app.models.expense import Expense
from app.models.sale import PaymentMethod, Sale, SaleStatus
from app.models.shop import Shop
from app.models.stock_lot import StockLotAllocation


class AccountingError(Exception):
    """Raised when a source transaction cannot be posted safely."""


DEFAULT_CHART = (
    ("1000", "Cash on hand", AccountType.ASSET),
    ("1010", "M-Pesa clearing", AccountType.ASSET),
    ("1020", "Bank", AccountType.ASSET),
    ("1100", "Inventory", AccountType.ASSET),
    ("1200", "Accounts receivable", AccountType.ASSET),
    ("2000", "Accounts payable", AccountType.LIABILITY),
    ("3000", "Owner capital", AccountType.EQUITY),
    ("3100", "Opening balance equity", AccountType.EQUITY),
    ("4000", "Sales revenue", AccountType.REVENUE),
    ("5000", "Cost of goods sold", AccountType.EXPENSE),
    ("5100", "Operating expenses", AccountType.EXPENSE),
    ("5200", "Inventory write-offs", AccountType.EXPENSE),
    ("5300", "Staff consumption", AccountType.EXPENSE),
)


def ensure_default_chart(db: Session, shop_id: int) -> dict[str, Account]:
    shop = db.scalar(select(Shop).where(Shop.id == shop_id).with_for_update())
    if shop is None:
        raise AccountingError("Shop not found while preparing its chart of accounts")

    accounts = {
        account.code: account
        for account in db.scalars(select(Account).where(Account.shop_id == shop_id)).all()
    }
    for code, name, account_type in DEFAULT_CHART:
        account = accounts.get(code)
        if account is None:
            account = Account(
                shop_id=shop_id,
                code=code,
                name=name,
                account_type=account_type.value,
                is_system=True,
                is_active=True,
            )
            db.add(account)
            accounts[code] = account
        elif (
            account.name != name
            or account.account_type != account_type.value
            or not account.is_system
        ):
            raise AccountingError(
                f"Default account {code} conflicts with the configured chart of accounts"
            )
        elif not account.is_active:
            raise AccountingError(f"Required default account {code} is inactive")
    db.flush()
    return accounts


def _create_or_verify_entry(
    db: Session,
    *,
    shop_id: int,
    entry_date: date,
    source_type: str,
    source_id: int,
    description: str,
    created_by_user_id: int,
    lines: list[tuple[str, Decimal, Decimal, str | None]],
) -> JournalEntry:
    if len(lines) < 2:
        raise AccountingError("A journal entry must contain at least two lines")
    for _, debit, credit, _ in lines:
        if (
            not debit.is_finite()
            or not credit.is_finite()
            or debit < 0
            or credit < 0
            or debit.quantize(Decimal("0.01")) != debit
            or credit.quantize(Decimal("0.01")) != credit
            or (debit > 0) == (credit > 0)
        ):
            raise AccountingError("Each journal line must have one positive debit or credit")
    debit_total = sum((debit for _, debit, _, _ in lines), Decimal("0.00"))
    credit_total = sum((credit for _, _, credit, _ in lines), Decimal("0.00"))
    if debit_total <= 0 or debit_total != credit_total:
        raise AccountingError("Journal entry debits and credits must be equal and greater than zero")

    accounts = ensure_default_chart(db, shop_id)
    missing_accounts = {code for code, _, _, _ in lines} - accounts.keys()
    if missing_accounts:
        raise AccountingError(
            f"Journal mapping references missing accounts: {', '.join(sorted(missing_accounts))}"
        )
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise AccountingError("Shop not found while preparing a journal entry")
    query = (
        select(JournalEntry)
        .where(
            JournalEntry.shop_id == shop_id,
            JournalEntry.source_type == source_type,
            JournalEntry.source_id == source_id,
        )
        .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
    )
    existing = db.scalar(query)
    if existing is not None:
        actual_lines = sorted(
            [
                (
                    line.account.code,
                    Decimal(line.debit),
                    Decimal(line.credit),
                    line.description,
                )
                for line in existing.lines
            ],
            key=lambda line: (line[0], line[1], line[2], line[3] or ""),
        )
        expected_lines = sorted(
            lines,
            key=lambda line: (line[0], line[1], line[2], line[3] or ""),
        )
        if (
            existing.entry_date != entry_date
            or existing.currency != shop.currency
            or existing.description != description
            or actual_lines != expected_lines
        ):
            raise AccountingError(
                f"Source {source_type} #{source_id} was already posted with different values"
            )
        return existing

    entry = JournalEntry(
        shop_id=shop_id,
        entry_date=entry_date,
        currency=shop.currency,
        source_type=source_type,
        source_id=source_id,
        description=description[:255],
        created_by_user_id=created_by_user_id,
    )
    entry.lines = [
        JournalLine(
            account=accounts[code],
            debit=debit,
            credit=credit,
            description=line_description,
        )
        for code, debit, credit, line_description in lines
    ]
    db.add(entry)
    db.flush()
    return entry


def post_completed_sale(db: Session, sale: Sale) -> JournalEntry:
    if sale.status != SaleStatus.COMPLETED:
        raise AccountingError("Only completed sales may be posted to the general journal")
    if not sale.items:
        raise AccountingError("A completed sale without line items cannot be posted")
    if sale.total <= 0:
        raise AccountingError("A completed sale must have a positive total to be posted")
    if any(not item.cost_is_known_at_sale for item in sale.items):
        raise AccountingError("Sale cost data is incomplete; the sale cannot be posted")

    if getattr(sale, "is_credit", False):
        debit_account = "1200"
        debit_desc = "Accounts receivable"
    else:
        debit_account = (
            "1000"
            if sale.payment_method == PaymentMethod.CASH
            else "1010"
            if sale.payment_method
            in {
                PaymentMethod.MPESA,
                PaymentMethod.POCHI,
                PaymentMethod.TILL,
                PaymentMethod.PAYBILL,
            }
            else None
        )
        if debit_account is None:
            raise AccountingError(f"Unsupported sale payment method: {sale.payment_method}")
        debit_desc = "Sale proceeds"

    db.flush()
    sale_item_ids = [item.id for item in sale.items]
    allocation_totals = {
        row.sale_item_id: (int(row.quantity), Decimal(row.cost_total))
        for row in db.execute(
            select(
                StockLotAllocation.sale_item_id,
                func.sum(StockLotAllocation.quantity).label("quantity"),
                func.sum(
                    StockLotAllocation.unit_cost * StockLotAllocation.quantity
                ).label("cost_total"),
            )
            .where(StockLotAllocation.sale_item_id.in_(sale_item_ids))
            .group_by(StockLotAllocation.sale_item_id)
        )
    }
    if any(
        allocation_totals.get(item.id, (0, Decimal("0.00")))[0] != item.quantity
        for item in sale.items
    ):
        raise AccountingError(
            "Sale inventory-cost allocations are incomplete; the sale cannot be posted"
        )
    cost_of_goods_sold = sum(
        (allocation_totals[item.id][1] for item in sale.items),
        Decimal("0.00"),
    )
    lines: list[tuple[str, Decimal, Decimal, str | None]] = [
        (debit_account, Decimal(sale.total), Decimal("0.00"), debit_desc),
        ("4000", Decimal("0.00"), Decimal(sale.total), "Sales revenue"),
    ]
    if cost_of_goods_sold:
        lines.extend(
            [
                ("5000", cost_of_goods_sold, Decimal("0.00"), "Cost of goods sold"),
                ("1100", Decimal("0.00"), cost_of_goods_sold, "Inventory relieved"),
            ]
        )
    return _create_or_verify_entry(
        db,
        shop_id=sale.shop_id,
        entry_date=sale.created_at.date(),
        source_type="sale",
        source_id=sale.id,
        description=f"Sale #{sale.id}",
        created_by_user_id=sale.cashier_id,
        lines=lines,
    )


def post_customer_payment(db: Session, payment: CustomerPayment) -> JournalEntry:
    if payment.amount <= 0:
        raise AccountingError("Payment amount must be greater than zero")
    cash_account = (
        "1000"
        if payment.payment_method == PaymentMethod.CASH
        else "1010"
        if payment.payment_method
        in {
            PaymentMethod.MPESA,
            PaymentMethod.POCHI,
            PaymentMethod.TILL,
            PaymentMethod.PAYBILL,
        }
        else None
    )
    if cash_account is None:
        raise AccountingError(f"Unsupported customer payment method: {payment.payment_method}")

    entry_date = (
        payment.created_at.date()
        if hasattr(payment.created_at, "date")
        else date.today()
    )
    return _create_or_verify_entry(
        db,
        shop_id=payment.shop_id,
        entry_date=entry_date,
        source_type="customer_payment",
        source_id=payment.id,
        description=f"Payment for Sale #{payment.sale_id} from Customer #{payment.customer_id}",
        created_by_user_id=payment.recorded_by_user_id,
        lines=[
            (
                cash_account,
                Decimal(payment.amount),
                Decimal("0.00"),
                f"Collection via {payment.payment_method.value}",
            ),
            (
                "1200",
                Decimal("0.00"),
                Decimal(payment.amount),
                f"Receivable reduction for Sale #{payment.sale_id}",
            ),
        ],
    )


def post_expense(db: Session, expense: Expense, shop_id: int) -> JournalEntry:
    if expense.amount <= 0:
        raise AccountingError("Expense amount must be greater than zero")
    cash_account = {"cash": "1000", "bank": "1020"}.get(expense.funding_source)
    if cash_account is None:
        raise AccountingError(f"Unsupported expense funding source: {expense.funding_source}")
    return _create_or_verify_entry(
        db,
        shop_id=shop_id,
        entry_date=expense.created_at.date(),
        source_type="expense",
        source_id=expense.id,
        description=f"Expense #{expense.id}: {expense.category}",
        created_by_user_id=expense.user_id,
        lines=[
            ("5100", Decimal(expense.amount), Decimal("0.00"), expense.category[:255]),
            (cash_account, Decimal("0.00"), Decimal(expense.amount), expense.funding_source),
        ],
    )
