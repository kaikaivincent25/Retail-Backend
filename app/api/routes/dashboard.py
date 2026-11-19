from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import require_cashier, require_manager
from app.core.business_time import business_day_bounds, business_today
from app.core.database import get_db
from app.models.cash_session import CashSession, SessionStatus
from app.models.customer_order import CustomerOrder, CustomerOrderStatus, OrderPaymentStatus
from app.models.expense import Expense
from app.models.product import Product
from app.models.sale import Sale, SaleStatus
from app.models.stock_movement import MovementType, StockMovement
from app.models.user import User
from app.models.variant import Variant
from app.schemas.dashboard import (
    CashierDashboardSummary,
    CreditSaleSummary,
    DashboardOrderSummary,
    DashboardSummary,
    TopProduct,
)
from app.services.reporting import summarize_period
from app.services.cash_sessions import get_open_session

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _online_order_summary(db: Session, shop_id: int) -> dict:
    terminal_statuses = (
        CustomerOrderStatus.COMPLETED,
        CustomerOrderStatus.REJECTED,
        CustomerOrderStatus.CANCELLED,
    )
    pending_count = db.scalar(
        select(func.count(CustomerOrder.id)).where(
            CustomerOrder.shop_id == shop_id,
            CustomerOrder.status == CustomerOrderStatus.PENDING,
        )
    ) or 0
    active_count = db.scalar(
        select(func.count(CustomerOrder.id)).where(
            CustomerOrder.shop_id == shop_id,
            CustomerOrder.status.not_in(terminal_statuses),
        )
    ) or 0
    awaiting_payment_count = db.scalar(
        select(func.count(CustomerOrder.id)).where(
            CustomerOrder.shop_id == shop_id,
            CustomerOrder.payment_status != OrderPaymentStatus.PAID,
            CustomerOrder.status.not_in(
                (CustomerOrderStatus.REJECTED, CustomerOrderStatus.CANCELLED)
            ),
        )
    ) or 0
    recent_orders = db.scalars(
        select(CustomerOrder)
        .where(CustomerOrder.shop_id == shop_id)
        .order_by(CustomerOrder.created_at.desc(), CustomerOrder.id.desc())
        .limit(6)
    ).all()
    return {
        "pending_orders_count": pending_count,
        "active_orders_count": active_count,
        "orders_awaiting_payment_count": awaiting_payment_count,
        "recent_orders": [
            DashboardOrderSummary(
                id=order.id,
                order_number=order.order_number,
                customer_name=order.customer_name,
                status=order.status,
                fulfilment=order.fulfilment,
                payment_method=order.payment_method,
                payment_status=order.payment_status,
                total=order.total,
                created_at=order.created_at,
            )
            for order in recent_orders
        ],
    }


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    today = business_today()
    start, _ = business_day_bounds(today)
    _, end = business_day_bounds(today)
    result = summarize_period(db, user.shop_id, today, today, include_report_details=False)
    credit_sales_total, credit_sales_count = db.execute(
        select(
            func.coalesce(func.sum(Sale.total), 0),
            func.count(Sale.id),
        ).where(
            Sale.shop_id == user.shop_id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.is_credit.is_(True),
            Sale.created_at >= start,
            Sale.created_at < end,
        )
    ).one()
    recent_credit_sales = db.scalars(
        select(Sale)
        .options(joinedload(Sale.customer), selectinload(Sale.payments))
        .where(
            Sale.shop_id == user.shop_id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.is_credit.is_(True),
            Sale.created_at >= start,
            Sale.created_at < end,
        )
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(8)
    ).all()
    credit_sale_summaries: list[CreditSaleSummary] = []
    for sale in recent_credit_sales:
        amount_paid = sum(
            (payment.amount for payment in sale.payments), Decimal("0.00")
        )
        credit_sale_summaries.append(
            CreditSaleSummary(
                id=sale.id,
                customer_name=sale.customer.full_name if sale.customer else "Customer unavailable",
                total=sale.total,
                amount_paid=amount_paid,
                balance=max(sale.total - amount_paid, Decimal("0.00")),
                due_date=sale.due_date,
                created_at=sale.created_at,
            )
        )
    return DashboardSummary(
        date=result["start_date"],
        total_sales=result["total_sales"],
        credit_sales_total=credit_sales_total,
        credit_sales_count=credit_sales_count,
        recent_credit_sales=credit_sale_summaries,
        **_online_order_summary(db, user.shop_id),
        expense_total=result["expense_total"],
        staff_consumption_total=result["staff_consumption_total"],
        net_sales=result["net_sales"],
        transaction_count=result["transaction_count"],
        estimated_profit=result["estimated_profit"],
        cost_of_goods_sold=result["cost_of_goods_sold"],
        gross_profit=result["gross_profit"],
        cost_data_complete=result["cost_data_complete"],
        profit_status=result["profit_status"],
        low_stock_count=result["low_stock_count"],
        top_products=[TopProduct(**p) for p in result["top_products"]],
    )


@router.get("/cashier-summary", response_model=CashierDashboardSummary)
def cashier_dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    today = business_today()
    start, _ = business_day_bounds(today)
    _, end = business_day_bounds(today)
    shop_sales = (Sale.shop_id == user.shop_id,)

    total_sales, transaction_count = db.execute(
        select(
            func.coalesce(func.sum(Sale.total), 0),
            func.count(Sale.id),
        ).where(
            *shop_sales,
            Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start,
            Sale.created_at < end,
        )
    ).one()

    expense_total = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .join(CashSession, CashSession.id == Expense.session_id)
        .where(
            CashSession.shop_id == user.shop_id,
            Expense.created_at >= start,
            Expense.created_at < end,
        )
    ) or 0

    staff_consumption_total = db.scalar(
        select(
            func.coalesce(
                func.sum(-StockMovement.quantity * StockMovement.unit_cost_at_time), 0
            )
        )
        .join(Variant, Variant.id == StockMovement.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == user.shop_id,
            StockMovement.movement_type == MovementType.STAFF_CONSUMPTION,
            StockMovement.created_at >= start,
            StockMovement.created_at < end,
        )
    ) or 0

    recent_sales = db.scalars(
        select(Sale)
        .where(*shop_sales)
        .order_by(Sale.created_at.desc())
        .limit(8)
    ).all()
    recent_sessions = db.scalars(
        select(CashSession)
        .where(
            CashSession.shop_id == user.shop_id,
            CashSession.status == SessionStatus.CLOSED,
        )
        .order_by(CashSession.closed_at.desc())
        .limit(5)
    ).all()

    return CashierDashboardSummary(
        date=today.isoformat(),
        total_sales=total_sales,
        expense_total=expense_total,
        staff_consumption_total=staff_consumption_total,
        net_sales=total_sales - expense_total,
        transaction_count=transaction_count,
        current_session=get_open_session(db, user.shop_id),
        recent_sales=recent_sales,
        recent_sessions=recent_sessions,
        **_online_order_summary(db, user.shop_id),
    )
