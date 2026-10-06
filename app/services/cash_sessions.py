from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityAction
from app.services.audit import log_activity
from app.models.cash_session import CashSession, SessionStatus
from app.models.expense import Expense
from app.models.shop import Shop
from app.models.sale import PaymentMethod, Sale, SaleStatus


class CashSessionError(Exception):
    pass


def get_open_session(
    db: Session, shop_id: int, *, lock: bool = False
) -> CashSession | None:
    query = select(CashSession).where(
        CashSession.shop_id == shop_id, CashSession.status == SessionStatus.OPEN
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query.order_by(CashSession.id.desc()))


def open_session(db: Session, user_id: int, shop_id: int) -> CashSession:
    # Serialize opening attempts for a shop, including concurrent requests.
    shop = db.scalar(select(Shop.id).where(Shop.id == shop_id).with_for_update())
    if shop is None:
        raise CashSessionError("Shop not found")
    if get_open_session(db, shop_id) is not None:
        db.rollback()
        raise CashSessionError("The shop already has an open cash session")

    previous_close = db.scalar(
        select(CashSession.closing_cash)
        .where(
            CashSession.shop_id == shop_id,
            CashSession.status == SessionStatus.CLOSED,
            CashSession.closing_cash.is_not(None),
        )
        .order_by(CashSession.closed_at.desc(), CashSession.id.desc())
        .limit(1)
    )
    session = CashSession(
        shop_id=shop_id,
        user_id=user_id,
        opening_cash=previous_close if previous_close is not None else Decimal("0.00"),
    )
    db.add(session)
    db.flush()  # assigns session.id without committing yet

    log_activity(
        db, user_id=user_id, action=ActivityAction.CASH_SESSION_OPENED,
        entity_type="cash_session", entity_id=session.id,
    )

    db.commit()
    db.refresh(session)
    return session


def close_session(
    db: Session,
    session: CashSession,
    closing_cash: Decimal,
    closed_by_user_id: int | None = None,
) -> CashSession:
    session = db.scalar(
        select(CashSession)
        .where(CashSession.id == session.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None or session.status == SessionStatus.CLOSED:
        db.rollback()
        raise CashSessionError("This session is already closed")

    cash_sales_total = db.scalar(
        select(func.coalesce(func.sum(Sale.total), 0)).where(
            Sale.session_id == session.id,
            Sale.payment_method == PaymentMethod.CASH,
            Sale.status == SaleStatus.COMPLETED,
        )
    ) or Decimal("0.00")

    expenses_total = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.session_id == session.id
        )
    ) or Decimal("0.00")

    expected = session.opening_cash + cash_sales_total - expenses_total
    if closing_cash > expected:
        db.rollback()
        raise CashSessionError(
            f"Closing cash cannot exceed the expected amount of {expected}."
        )

    session.closing_cash = closing_cash
    session.expected_cash = expected
    session.difference = closing_cash - expected
    session.status = SessionStatus.CLOSED
    session.closed_at = func.now()

    log_activity(
        db,
        user_id=closed_by_user_id or session.user_id,
        action=ActivityAction.CASH_SESSION_CLOSED,
        entity_type="cash_session", entity_id=session.id,
        description=f"difference: {session.difference}",
    )

    db.commit()
    db.refresh(session)
    return session