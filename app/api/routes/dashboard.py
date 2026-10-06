from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier, require_manager
from app.core.database import get_db
from app.models.cash_session import CashSession, SessionStatus
from app.models.expense import Expense
from app.models.sale import Sale, SaleStatus
from app.models.user import User
from app.schemas.dashboard import (
    CashierDashboardSummary,
    DashboardSummary,
    TopProduct,
)
from app.services.reporting import summarize_period
from app.services.cash_sessions import get_open_session

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    today = date.today()
    result = summarize_period(db, user.shop_id, today, today)
    return DashboardSummary(
        date=result["start_date"],
        total_sales=result["total_sales"],
        expense_total=result["expense_total"],
        net_sales=result["net_sales"],
        transaction_count=result["transaction_count"],
        estimated_profit=result["estimated_profit"],
        low_stock_count=result["low_stock_count"],
        top_products=[TopProduct(**p) for p in result["top_products"]],
    )


@router.get("/cashier-summary", response_model=CashierDashboardSummary)
def cashier_dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    today = date.today()
    start = datetime.combine(today, time.min, tzinfo=timezone.utc)
    end = datetime.combine(today, time.max, tzinfo=timezone.utc)
    shop_sales = (Sale.shop_id == user.shop_id,)

    total_sales, transaction_count = db.execute(
        select(
            func.coalesce(func.sum(Sale.total), 0),
            func.count(Sale.id),
        ).where(
            *shop_sales,
            Sale.status == SaleStatus.COMPLETED,
            Sale.created_at >= start,
            Sale.created_at <= end,
        )
    ).one()

    expense_total = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .join(CashSession, CashSession.id == Expense.session_id)
        .where(
            CashSession.shop_id == user.shop_id,
            Expense.created_at >= start,
            Expense.created_at <= end,
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
        net_sales=total_sales - expense_total,
        transaction_count=transaction_count,
        current_session=get_open_session(db, user.shop_id),
        recent_sales=recent_sales,
        recent_sessions=recent_sessions,
    )