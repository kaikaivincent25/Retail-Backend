from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    account_type: str
    is_system: bool
    is_active: bool


class JournalLineRead(BaseModel):
    id: int
    account_code: str
    account_name: str
    account_type: str
    debit: Decimal
    credit: Decimal
    description: str | None


class JournalEntryRead(BaseModel):
    id: int
    entry_date: date
    currency: str
    source_type: str
    source_id: int
    description: str
    created_by_user_id: int
    created_at: datetime
    debit_total: Decimal
    credit_total: Decimal
    lines: list[JournalLineRead]


class ReceivablesCustomerSummary(BaseModel):
    customer_id: int
    customer_name: str
    phone: str | None
    credit_limit: Decimal | None
    outstanding_balance: Decimal
    overdue_balance: Decimal
    oldest_due_date: date | None
    open_invoices_count: int


class ReceivablesSummaryRead(BaseModel):
    total_outstanding: Decimal
    total_overdue: Decimal
    current: Decimal
    overdue_1_30: Decimal
    overdue_31_60: Decimal
    overdue_60_plus: Decimal
    customers: list[ReceivablesCustomerSummary]


class AccountingPerformanceRead(BaseModel):
    basis: str = "accrual"
    start_date: date
    end_date: date
    currency: str
    sales_revenue: Decimal
    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    operating_expenses: Decimal
    stock_adjustments: Decimal
    estimated_net_profit: Decimal
    notices: list[str]


class AccountingReconciliationRead(BaseModel):
    start_date: date
    end_date: date
    currency: str
    sales_cash: Decimal
    sales_mpesa: Decimal
    sales_credit: Decimal
    sales_total: Decimal
    collections_cash: Decimal
    collections_mpesa: Decimal
    collections_total: Decimal
    receivables_issued: Decimal
    receivables_collected: Decimal
    net_receivables_change: Decimal
    notices: list[str]
