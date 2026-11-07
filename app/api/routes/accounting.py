from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_manager
from app.core.database import get_db
from app.models.accounting import Account, JournalEntry, JournalLine
from app.models.customer import Customer
from app.models.customer_payment import CustomerPayment
from app.models.expense import Expense
from app.models.product import Product
from app.models.sale import PaymentMethod, Sale, SaleItem, SaleStatus
from app.models.shop import Shop
from app.models.stock_movement import MovementType, StockMovement
from app.models.user import User
from app.models.variant import Variant
from app.schemas.accounting import (
    AccountingPerformanceRead,
    AccountingReconciliationRead,
    AccountRead,
    JournalEntryRead,
    JournalLineRead,
    ReceivablesCustomerSummary,
    ReceivablesSummaryRead,
)
from app.services.accounting import ensure_default_chart

router = APIRouter(prefix="/accounting", tags=["Accounting"])


def _read_entry(entry: JournalEntry) -> JournalEntryRead:
    lines = [
        JournalLineRead(
            id=line.id,
            account_code=line.account.code,
            account_name=line.account.name,
            account_type=line.account.account_type,
            debit=line.debit,
            credit=line.credit,
            description=line.description,
        )
        for line in entry.lines
    ]
    return JournalEntryRead(
        id=entry.id,
        entry_date=entry.entry_date,
        currency=entry.currency,
        source_type=entry.source_type,
        source_id=entry.source_id,
        description=entry.description,
        created_by_user_id=entry.created_by_user_id,
        created_at=entry.created_at,
        debit_total=sum((line.debit for line in lines), start=0),
        credit_total=sum((line.credit for line in lines), start=0),
        lines=lines,
    )


@router.get("/accounts", response_model=list[AccountRead])
def list_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    accounts = ensure_default_chart(db, user.shop_id)
    db.commit()
    return sorted(accounts.values(), key=lambda account: account.code)


@router.get("/journal", response_model=list[JournalEntryRead])
def list_journal_entries(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must not be before start_date")
    query = (
        select(JournalEntry)
        .where(JournalEntry.shop_id == user.shop_id)
        .options(
            selectinload(JournalEntry.lines).selectinload(JournalLine.account)
        )
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
    )
    if start_date:
        query = query.where(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.where(JournalEntry.entry_date <= end_date)
    entries = db.scalars(query.offset(offset).limit(limit)).all()
    return [_read_entry(entry) for entry in entries]


@router.get("/journal/{entry_id}", response_model=JournalEntryRead)
def get_journal_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    entry = db.scalar(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id, JournalEntry.shop_id == user.shop_id)
        .options(
            selectinload(JournalEntry.lines).selectinload(JournalLine.account)
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return _read_entry(entry)


@router.get("/receivables", response_model=ReceivablesSummaryRead)
def get_receivables(
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    today = date.today()
    customers = db.scalars(
        select(Customer)
        .where(Customer.shop_id == user.shop_id)
        .order_by(Customer.full_name)
    ).all()

    sales = db.scalars(
        select(Sale)
        .options(selectinload(Sale.payments))
        .where(
            Sale.shop_id == user.shop_id,
            Sale.is_credit.is_(True),
            Sale.status == SaleStatus.COMPLETED,
        )
    ).all()

    sales_by_customer: dict[int, list[Sale]] = {}
    for s in sales:
        if s.customer_id:
            sales_by_customer.setdefault(s.customer_id, []).append(s)

    total_outstanding = Decimal("0.00")
    total_overdue = Decimal("0.00")
    current = Decimal("0.00")
    overdue_1_30 = Decimal("0.00")
    overdue_31_60 = Decimal("0.00")
    overdue_60_plus = Decimal("0.00")

    customer_summaries: list[ReceivablesCustomerSummary] = []
    for c in customers:
        cust_sales = sales_by_customer.get(c.id, [])
        cust_outstanding = Decimal("0.00")
        cust_overdue = Decimal("0.00")
        oldest_due: date | None = None
        open_invoices = 0

        for s in cust_sales:
            paid = sum((p.amount for p in s.payments), Decimal("0.00"))
            bal = max(s.total - paid, Decimal("0.00"))
            if bal > 0:
                cust_outstanding += bal
                open_invoices += 1
                if s.due_date:
                    if oldest_due is None or s.due_date < oldest_due:
                        oldest_due = s.due_date
                    days_overdue = (today - s.due_date).days
                    if days_overdue > 0:
                        cust_overdue += bal
                        total_overdue += bal
                        if days_overdue <= 30:
                            overdue_1_30 += bal
                        elif days_overdue <= 60:
                            overdue_31_60 += bal
                        else:
                            overdue_60_plus += bal
                    else:
                        current += bal
                else:
                    current += bal

        total_outstanding += cust_outstanding

        if cust_outstanding > 0:
            customer_summaries.append(
                ReceivablesCustomerSummary(
                    customer_id=c.id,
                    customer_name=c.full_name,
                    phone=c.phone,
                    credit_limit=c.credit_limit,
                    outstanding_balance=cust_outstanding,
                    overdue_balance=cust_overdue,
                    oldest_due_date=oldest_due,
                    open_invoices_count=open_invoices,
                )
            )

    return ReceivablesSummaryRead(
        total_outstanding=total_outstanding,
        total_overdue=total_overdue,
        current=current,
        overdue_1_30=overdue_1_30,
        overdue_31_60=overdue_31_60,
        overdue_60_plus=overdue_60_plus,
        customers=customer_summaries,
    )


@router.get("/performance", response_model=AccountingPerformanceRead)
def get_performance(
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    today = date.today()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = date(end_date.year, end_date.month, 1)
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must not be before start_date")

    shop = db.get(Shop, user.shop_id)
    currency = shop.currency if shop else "KES"

    start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, time.max, tzinfo=timezone.utc)

    # Sales revenue (completed sales in period)
    sales_revenue = db.scalar(
        select(func.coalesce(func.sum(Sale.total), 0)).where(
            Sale.shop_id == user.shop_id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
        )
    ) or Decimal("0.00")

    # COGS for completed sales in period
    cogs = db.scalar(
        select(func.coalesce(func.sum(SaleItem.unit_cost_at_sale * SaleItem.quantity), 0))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.shop_id == user.shop_id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
        )
    ) or Decimal("0.00")

    # Expenses in period
    expenses = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.created_at >= start_dt,
            Expense.created_at <= end_dt,
        )
    ) or Decimal("0.00")

    # Stock adjustments / staff use in period
    staff_use = db.scalar(
        select(
            func.coalesce(
                func.sum(-StockMovement.quantity * func.coalesce(StockMovement.unit_cost_at_time, 0)),
                0,
            )
        )
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == user.shop_id,
            StockMovement.movement_type == MovementType.STAFF_CONSUMPTION,
            StockMovement.created_at >= start_dt,
            StockMovement.created_at <= end_dt,
        )
    ) or Decimal("0.00")

    stock_loss = db.scalar(
        select(
            func.coalesce(
                func.sum(-StockMovement.quantity * func.coalesce(StockMovement.unit_cost_at_time, 0)),
                0,
            )
        )
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == user.shop_id,
            or_(
                StockMovement.movement_type == MovementType.DAMAGE,
                (StockMovement.movement_type == MovementType.ADJUSTMENT)
                & (StockMovement.quantity < 0),
            ),
            StockMovement.created_at >= start_dt,
            StockMovement.created_at <= end_dt,
        )
    ) or Decimal("0.00")

    gross_profit = sales_revenue - cogs
    stock_adjustments = staff_use + stock_loss
    net_profit = gross_profit - expenses - stock_adjustments

    notices = [
        "Accrual basis: Sales revenue is recognized when sales are completed, including credit sales.",
        "Cost of Goods Sold is derived from FIFO stock lot allocations.",
        "Gross Profit = Sales Revenue - Cost of Goods Sold.",
        "Estimated Net Profit = Gross Profit - Operating Expenses - Stock Adjustments.",
        "Operational estimate preview: statutory balance sheet is omitted until accounting cutover and verified opening balances are configured.",
    ]

    return AccountingPerformanceRead(
        basis="accrual",
        start_date=start_date,
        end_date=end_date,
        currency=currency,
        sales_revenue=sales_revenue,
        cost_of_goods_sold=cogs,
        gross_profit=gross_profit,
        operating_expenses=expenses,
        stock_adjustments=stock_adjustments,
        estimated_net_profit=net_profit,
        notices=notices,
    )


@router.get("/reconciliation", response_model=AccountingReconciliationRead)
def get_reconciliation(
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    today = date.today()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = date(end_date.year, end_date.month, 1)
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must not be before start_date")

    shop = db.get(Shop, user.shop_id)
    currency = shop.currency if shop else "KES"

    start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, time.max, tzinfo=timezone.utc)

    # Sales by tender in period
    sales = db.scalars(
        select(Sale).where(
            Sale.shop_id == user.shop_id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
        )
    ).all()

    sales_cash = sum(
        (s.total for s in sales if not s.is_credit and s.payment_method == PaymentMethod.CASH),
        Decimal("0.00"),
    )
    sales_mpesa = sum(
        (
            s.total
            for s in sales
            if not s.is_credit
            and s.payment_method
            in {
                PaymentMethod.MPESA,
                PaymentMethod.POCHI,
                PaymentMethod.TILL,
                PaymentMethod.PAYBILL,
            }
        ),
        Decimal("0.00"),
    )
    sales_credit = sum(
        (s.total for s in sales if s.is_credit),
        Decimal("0.00"),
    )
    sales_total = sales_cash + sales_mpesa + sales_credit

    # Collections by tender in period
    payments = db.scalars(
        select(CustomerPayment).where(
            CustomerPayment.shop_id == user.shop_id,
            CustomerPayment.created_at >= start_dt,
            CustomerPayment.created_at <= end_dt,
        )
    ).all()

    collections_cash = sum(
        (p.amount for p in payments if p.payment_method == PaymentMethod.CASH),
        Decimal("0.00"),
    )
    collections_mpesa = sum(
        (p.amount for p in payments if p.payment_method != PaymentMethod.CASH),
        Decimal("0.00"),
    )
    collections_total = collections_cash + collections_mpesa

    receivables_issued = sales_credit
    receivables_collected = collections_total
    net_receivables_change = receivables_issued - receivables_collected

    notices = [
        "Sales are reported by transaction date; collections are reported by payment date.",
        "Credit sales create accounts receivable; customer payments reduce accounts receivable.",
        "Cash collections from customer repayments are counted into expected till cash for active cash sessions.",
    ]

    return AccountingReconciliationRead(
        start_date=start_date,
        end_date=end_date,
        currency=currency,
        sales_cash=sales_cash,
        sales_mpesa=sales_mpesa,
        sales_credit=sales_credit,
        sales_total=sales_total,
        collections_cash=collections_cash,
        collections_mpesa=collections_mpesa,
        collections_total=collections_total,
        receivables_issued=receivables_issued,
        receivables_collected=receivables_collected,
        net_receivables_change=net_receivables_change,
        notices=notices,
    )
