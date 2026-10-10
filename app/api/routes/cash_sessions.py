from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier
from app.core.database import get_db
from app.models.cash_session import CashSession
from app.models.user import User
from app.schemas.cash_session import (
    CashDepositCreate,
    CashDepositRead,
    CashDepositSummary,
    CashSessionRead,
    SessionClose,
    SessionOpen,
)
from app.services.cash_sessions import (
    CashSessionError,
    close_session,
    get_depositable_cash,
    get_open_session,
    list_cash_deposits,
    open_session,
    record_cash_deposit,
)

router = APIRouter(prefix="/cash-sessions", tags=["Cash Sessions"])


@router.get("", response_model=list[CashSessionRead])
def list_cash_sessions(
    user_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    query = select(CashSession).where(CashSession.shop_id == user.shop_id)
    if user.role.value != "cashier" and user_id is not None:
        query = query.where(CashSession.user_id == user_id)
    return db.scalars(query.order_by(CashSession.created_at.desc())).all()


@router.get("/current", response_model=CashSessionRead | None)
def current_session(db: Session = Depends(get_db), user: User = Depends(require_cashier)):
    return get_open_session(db, user.shop_id)


@router.get("/deposits", response_model=CashDepositSummary)
def cash_deposits(db: Session = Depends(get_db), user: User = Depends(require_cashier)):
    deposits = [
        {
            **CashDepositRead.model_validate(
                {**deposit.__dict__, "user_name": user_name}
            ).model_dump(),
        }
        for deposit, user_name in list_cash_deposits(db, user.shop_id)
    ]
    return {
        "available_cash": get_depositable_cash(db, user.shop_id),
        "deposits": deposits,
    }


@router.post("/deposits", response_model=CashDepositRead, status_code=201)
def create_cash_deposit(
    payload: CashDepositCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    try:
        deposit = record_cash_deposit(
            db,
            shop_id=user.shop_id,
            user_id=user.id,
            amount=Decimal(str(payload.amount)),
            frequency=payload.frequency,
        )
    except CashSessionError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        **CashDepositRead.model_validate(
            {**deposit.__dict__, "user_name": user.full_name}
        ).model_dump(),
    }


@router.post("/open", response_model=CashSessionRead, status_code=201)
def open_cash_session(
    payload: SessionOpen,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    try:
        return open_session(
            db,
            user_id=user.id,
            shop_id=user.shop_id,
        )
    except CashSessionError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/close", response_model=CashSessionRead)
def close_cash_session(
    payload: SessionClose,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    session = get_open_session(db, user.shop_id, lock=True)
    if session is None:
        raise HTTPException(status_code=422, detail="You have no open cash session")

    try:
        return close_session(
            db,
            session,
            closing_cash=Decimal(str(payload.closing_cash)),
            closed_by_user_id=user.id,
        )
    except CashSessionError as e:
        raise HTTPException(status_code=422, detail=str(e))