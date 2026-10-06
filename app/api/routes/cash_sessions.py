from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier, require_manager
from app.core.database import get_db
from app.models.cash_session import CashSession
from app.models.user import User
from app.schemas.cash_session import CashSessionRead, SessionClose, SessionOpen
from app.services.cash_sessions import CashSessionError, close_session, get_open_session, open_session

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