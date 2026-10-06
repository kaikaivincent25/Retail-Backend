from decimal import Decimal

from pydantic import BaseModel

from app.schemas.dashboard import TopProduct


class DailyTotal(BaseModel):
    date: str
    total: Decimal
    expense_total: Decimal
    net_sales: Decimal


class PeriodReport(BaseModel):
    start_date: str
    end_date: str
    total_sales: Decimal
    expense_total: Decimal
    net_sales: Decimal
    transaction_count: int
    estimated_profit: Decimal
    low_stock_count: int
    top_products: list[TopProduct]
    daily_breakdown: list[DailyTotal]