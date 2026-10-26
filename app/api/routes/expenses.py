from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier
from app.core.database import get_db
from app.models.expense import Expense
from app.models.user import User, UserRole
from app.models.sale import PaymentMethod, Sale, SaleStatus
from app.schemas.expense import ExpenseCreate, ExpenseRead
from app.services.cash_sessions import get_open_session

router = APIRouter(prefix="/expenses", tags=["Expenses"])


@router.post("", response_model=ExpenseRead, status_code=201)
def create_expense(
    payload: ExpenseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    open_session = get_open_session(db, user.shop_id, lock=True)
    if open_session is None:
        raise HTTPException(
            status_code=422,
            detail="You must have an open cash session to log an expense",
        )

    cash_sales = db.scalar(
        select(func.coalesce(func.sum(Sale.total), 0)).where(
            Sale.session_id == open_session.id,
            Sale.payment_method == PaymentMethod.CASH,
            Sale.status == SaleStatus.COMPLETED,
        )
    ) or Decimal("0.00")
    if open_session.opening_cash <= 0 and cash_sales <= 0:
        raise HTTPException(
            status_code=422,
            detail="Record an opening float or complete a cash sale before recording an expense.",
        )
    if payload.funding_source == "cash":
        cash_expenses = db.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.session_id == open_session.id,
                Expense.funding_source == "cash",
            )
        ) or Decimal("0.00")
        available_cash = open_session.opening_cash + cash_sales - cash_expenses
        if payload.amount > available_cash:
            raise HTTPException(
                status_code=422,
                detail=f"Expense exceeds available till cash of {available_cash}.",
            )

    expense = Expense(
        user_id=user.id,
        session_id=open_session.id,
        **payload.model_dump(),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return {**ExpenseRead.model_validate(expense).model_dump(), "user_name": user.full_name}


@router.get("", response_model=list[ExpenseRead])
def list_expenses(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    query = (
        select(Expense, User.full_name)
        .join(User, User.id == Expense.user_id)
        .where(User.shop_id == user.shop_id)
        .order_by(Expense.created_at.desc())
    )
    if user.role == UserRole.CASHIER:
        query = query.where(Expense.user_id == user.id)

    return [
        {**ExpenseRead.model_validate(expense).model_dump(), "user_name": user_name}
        for expense, user_name in db.execute(query).all()
    ]


@router.get("/mine", response_model=list[ExpenseRead])
def my_expenses(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    query = select(Expense).where(Expense.user_id == user.id).order_by(Expense.created_at.desc())
    return db.scalars(query).all()
