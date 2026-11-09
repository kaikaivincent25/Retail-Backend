from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.sale import PaymentMethod, SaleStatus
from app.schemas.cash_session import CashSessionRead


class TopProduct(BaseModel):
    variant_id: int
    variant_name: str
    quantity_sold: int


class CreditSaleSummary(BaseModel):
    id: int
    customer_name: str
    total: Decimal
    amount_paid: Decimal
    balance: Decimal
    due_date: date | None
    created_at: datetime


class DashboardSummary(BaseModel):
    date: str
    total_sales: Decimal
    credit_sales_total: Decimal
    credit_sales_count: int
    recent_credit_sales: list[CreditSaleSummary]
    expense_total: Decimal
    staff_consumption_total: Decimal = Decimal("0.00")
    net_sales: Decimal
    transaction_count: int
    estimated_profit: Decimal
    cost_of_goods_sold: Decimal = Decimal("0.00")
    gross_profit: Decimal = Decimal("0.00")
    cost_data_complete: bool = False
    profit_status: str = "incomplete"
    low_stock_count: int
    top_products: list[TopProduct]


class CashierSaleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    total: Decimal
    payment_method: PaymentMethod
    status: SaleStatus
    created_at: datetime


class CashierDashboardSummary(BaseModel):
    date: str
    total_sales: Decimal
    expense_total: Decimal
    staff_consumption_total: Decimal = Decimal("0.00")
    net_sales: Decimal
    transaction_count: int
    current_session: CashSessionRead | None
    recent_sales: list[CashierSaleSummary]
    recent_sessions: list[CashSessionRead]
