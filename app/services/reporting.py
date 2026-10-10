from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.cash_session import CashSession
from app.models.expense import Expense
from app.models.sale import Sale, SaleItem, SaleStatus
from app.models.stock_movement import MovementType, StockMovement
from app.models.variant import Variant


def summarize_period(db: Session, shop_id: int, start: date, end: date) -> dict:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)

    sales_query = select(Sale).where(
        Sale.shop_id == shop_id,
        Sale.status == SaleStatus.COMPLETED,
        Sale.created_at >= start_dt,
        Sale.created_at <= end_dt,
    )
    sales = db.scalars(sales_query).all()

    total_sales = sum((s.total for s in sales), Decimal("0.00"))
    transaction_count = len(sales)

    expense_query = (
        select(func.coalesce(func.sum(Expense.amount), 0))
        .join(CashSession, CashSession.id == Expense.session_id)
        .where(
            CashSession.shop_id == shop_id,
            Expense.created_at >= start_dt,
            Expense.created_at <= end_dt,
        )
    )
    expense_total = db.scalar(expense_query) or Decimal("0.00")

    staff_consumption_total = db.scalar(
        select(
            func.coalesce(
                func.sum(-StockMovement.quantity * StockMovement.unit_cost_at_time), 0
            )
        )
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == shop_id,
            StockMovement.movement_type == MovementType.STAFF_CONSUMPTION,
            StockMovement.created_at >= start_dt,
            StockMovement.created_at <= end_dt,
        )
    ) or Decimal("0.00")

    profit_query = (
        select(func.sum((SaleItem.unit_price - SaleItem.unit_cost_at_sale) * SaleItem.quantity))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.shop_id == shop_id, Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt, Sale.created_at <= end_dt,
        )
    )
    estimated_profit = db.scalar(profit_query) or Decimal("0.00")

    low_stock_count = db.scalar(
        select(func.count())
        .select_from(Variant)
        .join(Product)
        .where(Product.shop_id == shop_id, Variant.is_active.is_(True), Variant.quantity <= Variant.reorder_level)
    )

    top_query = (
        select(
            Variant.id.label("variant_id"), Variant.name.label("variant_name"),
            func.sum(SaleItem.quantity).label("quantity_sold"),
        )
        .join(SaleItem, SaleItem.variant_id == Variant.id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == shop_id, Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt, Sale.created_at <= end_dt,
        )
        .group_by(Variant.id, Variant.name)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(10)
    )
    top_products = [
        {"variant_id": r.variant_id, "variant_name": r.variant_name, "quantity_sold": int(r.quantity_sold)}
        for r in db.execute(top_query).all()
    ]

    daily_query = (
        select(func.date(Sale.created_at).label("day"), func.sum(Sale.total).label("total"))
        .where(
            Sale.shop_id == shop_id, Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt, Sale.created_at <= end_dt,
        )
        .group_by(func.date(Sale.created_at))
        .order_by(func.date(Sale.created_at))
    )
    daily_breakdown = [
        {
            "date": r.day.isoformat(),
            "total": Decimal(str(r.total)) if r.total is not None else Decimal("0.00"),
            "expense_total": Decimal("0.00"),
            "staff_consumption_total": Decimal("0.00"),
            "net_sales": Decimal(str(r.total)) if r.total is not None else Decimal("0.00"),
        }
        for r in db.execute(daily_query).all()
    ]

    daily_expense_query = (
        select(func.date(Expense.created_at).label("day"), func.sum(Expense.amount).label("total"))
        .join(CashSession, CashSession.id == Expense.session_id)
        .where(
            CashSession.shop_id == shop_id,
            Expense.created_at >= start_dt,
            Expense.created_at <= end_dt,
        )
        .group_by(func.date(Expense.created_at))
        .order_by(func.date(Expense.created_at))
    )
    daily_totals = {entry["date"]: entry for entry in daily_breakdown}
    for row in db.execute(daily_expense_query).all():
        day = row.day.isoformat()
        amount = Decimal(str(row.total)) if row.total is not None else Decimal("0.00")
        entry = daily_totals.setdefault(
            day,
            {
                "date": day,
                "total": Decimal("0.00"),
                "expense_total": Decimal("0.00"),
                "staff_consumption_total": Decimal("0.00"),
                "net_sales": Decimal("0.00"),
            },
        )
        entry["expense_total"] = amount
        entry["net_sales"] = entry["total"] - amount

    daily_staff_consumption_query = (
        select(
            func.date(StockMovement.created_at).label("day"),
            func.sum(-StockMovement.quantity * StockMovement.unit_cost_at_time).label("total"),
        )
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == shop_id,
            StockMovement.movement_type == MovementType.STAFF_CONSUMPTION,
            StockMovement.created_at >= start_dt,
            StockMovement.created_at <= end_dt,
        )
        .group_by(func.date(StockMovement.created_at))
        .order_by(func.date(StockMovement.created_at))
    )
    for row in db.execute(daily_staff_consumption_query).all():
        day = row.day.isoformat()
        amount = Decimal(str(row.total)) if row.total is not None else Decimal("0.00")
        entry = daily_totals.setdefault(
            day,
            {
                "date": day,
                "total": Decimal("0.00"),
                "expense_total": Decimal("0.00"),
                "staff_consumption_total": Decimal("0.00"),
                "net_sales": Decimal("0.00"),
            },
        )
        entry["staff_consumption_total"] = amount
    daily_breakdown = sorted(daily_totals.values(), key=lambda entry: entry["date"])

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_sales": total_sales.quantize(Decimal("0.01")),
        "expense_total": expense_total.quantize(Decimal("0.01")),
        "staff_consumption_total": staff_consumption_total.quantize(Decimal("0.01")),
        "net_sales": (total_sales - expense_total).quantize(Decimal("0.01")),
        "transaction_count": transaction_count,
        "estimated_profit": estimated_profit.quantize(Decimal("0.01")),
        "low_stock_count": low_stock_count,
        "top_products": top_products,
        "daily_breakdown": daily_breakdown,
    }