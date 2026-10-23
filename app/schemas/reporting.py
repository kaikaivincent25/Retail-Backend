from decimal import Decimal

from pydantic import BaseModel

class DailyTotal(BaseModel):
    date: str
    total: Decimal
    expense_total: Decimal
    staff_consumption_total: Decimal = Decimal("0.00")
    net_sales: Decimal


class ReportProduct(BaseModel):
    variant_id: int
    variant_name: str
    quantity_sold: int
    revenue: Decimal
    gross_profit: Decimal
    gross_margin_percent: Decimal | None = None
    cost_data_complete: bool


class PeriodComparison(BaseModel):
    start_date: str
    end_date: str
    total_sales: Decimal
    estimated_profit: Decimal
    cost_data_complete: bool
    sales_change: Decimal
    profit_change: Decimal
    sales_change_percent: Decimal | None = None


class PeriodReport(BaseModel):
    start_date: str
    end_date: str
    total_sales: Decimal
    expense_total: Decimal
    staff_consumption_total: Decimal = Decimal("0.00")
    net_sales: Decimal
    transaction_count: int
    estimated_profit: Decimal
    cost_of_goods_sold: Decimal = Decimal("0.00")
    gross_profit: Decimal = Decimal("0.00")
    cost_data_complete: bool = False
    profit_status: str = "incomplete"
    damage_total: Decimal = Decimal("0.00")
    comparison: PeriodComparison
    low_stock_count: int
    top_products: list[ReportProduct]
    loss_making_products: list[ReportProduct]
    daily_breakdown: list[DailyTotal]
