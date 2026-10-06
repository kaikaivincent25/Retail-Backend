from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.sale import PaymentMethod, SaleStatus
from app.schemas.cash_session import CashSessionRead


class TopProduct(BaseModel):
    variant_id: int
    variant_name: str
    quantity_sold: int


class DashboardSummary(BaseModel):
    date: str
    total_sales: Decimal
    expense_total: Decimal
    net_sales: Decimal
    transaction_count: int
    estimated_profit: Decimal
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
    net_sales: Decimal
    transaction_count: int
    current_session: CashSessionRead | None
    recent_sales: list[CashierSaleSummary]
    recent_sessions: list[CashSessionRead]