from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier
from app.core.database import get_db
from app.models.expense import Expense
from app.models.user import User, UserRole
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