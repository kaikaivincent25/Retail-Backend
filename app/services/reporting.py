from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.cash_session import CashSession
from app.models.expense import Expense
from app.models.sale import Sale, SaleItem, SaleStatus
from app.models.stock_movement import MovementType, StockMovement
from app.models.variant import Variant


def _period_financial_totals(db: Session, shop_id: int, start_dt: datetime, end_dt: datetime) -> dict:
    total_sales = db.scalar(
        select(func.coalesce(func.sum(Sale.total), 0)).where(
            Sale.shop_id == shop_id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
        )
    ) or Decimal("0.00")
    cogs = db.scalar(
        select(func.coalesce(func.sum(SaleItem.unit_cost_at_sale * SaleItem.quantity), 0))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.shop_id == shop_id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
        )
    ) or Decimal("0.00")
    expenses = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .join(CashSession, CashSession.id == Expense.session_id)
        .where(
            CashSession.shop_id == shop_id,
            Expense.created_at >= start_dt,
            Expense.created_at <= end_dt,
        )
    ) or Decimal("0.00")
    stock_use = db.scalar(
        select(func.coalesce(func.sum(-StockMovement.quantity * StockMovement.unit_cost_at_time), 0))
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == shop_id,
            StockMovement.movement_type == MovementType.STAFF_CONSUMPTION,
            StockMovement.created_at >= start_dt,
            StockMovement.created_at <= end_dt,
        )
    ) or Decimal("0.00")
    stock_loss = db.scalar(
        select(func.coalesce(func.sum(-StockMovement.quantity * StockMovement.unit_cost_at_time), 0))
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == shop_id,
            or_(
                StockMovement.movement_type == MovementType.DAMAGE,
                (StockMovement.movement_type == MovementType.ADJUSTMENT)
                & (StockMovement.quantity < 0),
            ),
            StockMovement.unit_cost_at_time.is_not(None),
            StockMovement.created_at >= start_dt,
            StockMovement.created_at <= end_dt,
        )
    ) or Decimal("0.00")
    incomplete_sales = db.scalar(
        select(func.count(SaleItem.id))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.shop_id == shop_id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            SaleItem.cost_is_known_at_sale.is_(False),
        )
    ) or 0
    incomplete_movements = db.scalar(
        select(func.count(StockMovement.id))
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == shop_id,
            or_(
                StockMovement.movement_type == MovementType.STAFF_CONSUMPTION,
                StockMovement.movement_type == MovementType.DAMAGE,
                (StockMovement.movement_type == MovementType.ADJUSTMENT)
                & (StockMovement.quantity < 0),
            ),
            StockMovement.unit_cost_at_time.is_(None),
            StockMovement.created_at >= start_dt,
            StockMovement.created_at <= end_dt,
        )
    ) or 0
    profit = total_sales - cogs - expenses - stock_use - stock_loss
    return {
        "total_sales": Decimal(total_sales),
        "estimated_profit": Decimal(profit),
        "cost_data_complete": incomplete_sales == 0 and incomplete_movements == 0,
    }


def summarize_period(
    db: Session,
    shop_id: int,
    start: date,
    end: date,
    include_report_details: bool = True,
) -> dict:
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

    cogs_query = (
        select(func.coalesce(func.sum(SaleItem.unit_cost_at_sale * SaleItem.quantity), 0))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.shop_id == shop_id, Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt, Sale.created_at <= end_dt,
        )
    )
    cost_of_goods_sold = db.scalar(cogs_query) or Decimal("0.00")
    incomplete_cost_count = db.scalar(
        select(func.count(SaleItem.id))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.shop_id == shop_id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            SaleItem.cost_is_known_at_sale.is_(False),
        )
    ) or 0

    uncosted_stock_use_count = db.scalar(
        select(func.count(StockMovement.id))
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == shop_id,
            or_(
                StockMovement.movement_type == MovementType.STAFF_CONSUMPTION,
                StockMovement.movement_type == MovementType.DAMAGE,
                (StockMovement.movement_type == MovementType.ADJUSTMENT)
                & (StockMovement.quantity < 0),
            ),
            StockMovement.created_at >= start_dt,
            StockMovement.created_at <= end_dt,
            StockMovement.unit_cost_at_time.is_(None),
        )
    ) or 0

    damage_total = db.scalar(
        select(func.coalesce(func.sum(-StockMovement.quantity * StockMovement.unit_cost_at_time), 0))
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == shop_id,
            or_(
                StockMovement.movement_type == MovementType.DAMAGE,
                (StockMovement.movement_type == MovementType.ADJUSTMENT)
                & (StockMovement.quantity < 0),
            ),
            StockMovement.created_at >= start_dt,
            StockMovement.created_at <= end_dt,
            StockMovement.unit_cost_at_time.is_not(None),
        )
    ) or Decimal("0.00")
    gross_profit = total_sales - cost_of_goods_sold
    estimated_profit = gross_profit - expense_total - staff_consumption_total - damage_total

    low_stock_count = db.scalar(
        select(func.count())
        .select_from(Variant)
        .join(Product)
        .where(Product.shop_id == shop_id, Variant.is_active.is_(True), Variant.quantity <= Variant.reorder_level)
    )

    product_gross_profit = func.sum(
        SaleItem.line_total - SaleItem.unit_cost_at_sale * SaleItem.quantity
    )
    product_revenue = func.sum(SaleItem.line_total)
    product_margin_percent = product_gross_profit / func.nullif(product_revenue, 0) * 100
    top_query = (
        select(
            Variant.id.label("variant_id"), Variant.name.label("variant_name"),
            func.sum(SaleItem.quantity).label("quantity_sold"),
            product_revenue.label("revenue"),
            product_gross_profit.label("gross_profit"),
            product_margin_percent.label("gross_margin_percent"),
            func.bool_and(SaleItem.cost_is_known_at_sale).label("cost_data_complete"),
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
        {
            "variant_id": r.variant_id,
            "variant_name": r.variant_name,
            "quantity_sold": int(r.quantity_sold),
            "revenue": r.revenue,
            "gross_profit": r.gross_profit,
            "gross_margin_percent": r.gross_margin_percent,
            "cost_data_complete": bool(r.cost_data_complete),
        }
        for r in db.execute(top_query).all()
    ]

    loss_query = top_query.with_only_columns(
        Variant.id.label("variant_id"),
        Variant.name.label("variant_name"),
        func.sum(SaleItem.quantity).label("quantity_sold"),
        product_revenue.label("revenue"),
        product_gross_profit.label("gross_profit"),
        product_margin_percent.label("gross_margin_percent"),
        func.bool_and(SaleItem.cost_is_known_at_sale).label("cost_data_complete"),
    ).having(
        func.bool_and(SaleItem.cost_is_known_at_sale),
        product_gross_profit < 0,
    ).order_by(None).order_by(
        product_gross_profit
    ).limit(5)
    loss_making_products = [
        {
            "variant_id": r.variant_id,
            "variant_name": r.variant_name,
            "quantity_sold": int(r.quantity_sold),
            "revenue": r.revenue,
            "gross_profit": r.gross_profit,
            "gross_margin_percent": r.gross_margin_percent,
            "cost_data_complete": bool(r.cost_data_complete),
        }
        for r in db.execute(loss_query).all()
    ] if include_report_details else []

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

    comparison = None
    if include_report_details:
        period_days = (end - start).days + 1
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=period_days - 1)
        previous_totals = _period_financial_totals(
            db,
            shop_id,
            datetime.combine(previous_start, time.min, tzinfo=timezone.utc),
            datetime.combine(previous_end, time.max, tzinfo=timezone.utc),
        )
        sales_change = total_sales - previous_totals["total_sales"]
        profit_change = estimated_profit - previous_totals["estimated_profit"]
        comparison = {
            "start_date": previous_start.isoformat(),
            "end_date": previous_end.isoformat(),
            "total_sales": previous_totals["total_sales"].quantize(Decimal("0.01")),
            "estimated_profit": previous_totals["estimated_profit"].quantize(Decimal("0.01")),
            "cost_data_complete": previous_totals["cost_data_complete"],
            "sales_change": sales_change.quantize(Decimal("0.01")),
            "profit_change": profit_change.quantize(Decimal("0.01")),
            "sales_change_percent": (
                (sales_change / abs(previous_totals["total_sales"]) * 100).quantize(Decimal("0.01"))
                if previous_totals["total_sales"] != 0 else None
            ),
        }

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_sales": total_sales.quantize(Decimal("0.01")),
        "expense_total": expense_total.quantize(Decimal("0.01")),
        "staff_consumption_total": staff_consumption_total.quantize(Decimal("0.01")),
        "net_sales": (total_sales - expense_total).quantize(Decimal("0.01")),
        "transaction_count": transaction_count,
        "estimated_profit": estimated_profit.quantize(Decimal("0.01")),
        "cost_of_goods_sold": Decimal(cost_of_goods_sold).quantize(Decimal("0.01")),
        "gross_profit": Decimal(gross_profit).quantize(Decimal("0.01")),
        "damage_total": Decimal(damage_total).quantize(Decimal("0.01")),
        "cost_data_complete": incomplete_cost_count == 0 and uncosted_stock_use_count == 0,
        "profit_status": (
            "incomplete" if incomplete_cost_count or uncosted_stock_use_count else
            "profit" if estimated_profit > 0 else
            "loss" if estimated_profit < 0 else "break_even"
        ),
        "comparison": comparison,
        "low_stock_count": low_stock_count,
        "top_products": top_products,
        "loss_making_products": loss_making_products,
        "daily_breakdown": daily_breakdown,
    }
