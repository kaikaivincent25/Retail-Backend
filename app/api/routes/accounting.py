from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_manager
from app.core.database import get_db
from app.models.accounting import Account, JournalEntry, JournalLine
from app.models.user import User
from app.schemas.accounting import AccountRead, JournalEntryRead, JournalLineRead
from app.services.accounting import ensure_default_chart

router = APIRouter(prefix="/accounting", tags=["Accounting"])


def _read_entry(entry: JournalEntry) -> JournalEntryRead:
    lines = [
        JournalLineRead(
            id=line.id,
            account_code=line.account.code,
            account_name=line.account.name,
            account_type=line.account.account_type,
            debit=line.debit,
            credit=line.credit,
            description=line.description,
        )
        for line in entry.lines
    ]
    return JournalEntryRead(
        id=entry.id,
        entry_date=entry.entry_date,
        currency=entry.currency,
        source_type=entry.source_type,
        source_id=entry.source_id,
        description=entry.description,
        created_by_user_id=entry.created_by_user_id,
        created_at=entry.created_at,
        debit_total=sum((line.debit for line in lines), start=0),
        credit_total=sum((line.credit for line in lines), start=0),
        lines=lines,
    )


@router.get("/accounts", response_model=list[AccountRead])
def list_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    accounts = ensure_default_chart(db, user.shop_id)
    db.commit()
    return sorted(accounts.values(), key=lambda account: account.code)


@router.get("/journal", response_model=list[JournalEntryRead])
def list_journal_entries(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must not be before start_date")
    query = (
        select(JournalEntry)
        .where(JournalEntry.shop_id == user.shop_id)
        .options(
            selectinload(JournalEntry.lines).selectinload(JournalLine.account)
        )
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
    )
    if start_date:
        query = query.where(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.where(JournalEntry.entry_date <= end_date)
    entries = db.scalars(query.offset(offset).limit(limit)).all()
    return [_read_entry(entry) for entry in entries]


@router.get("/journal/{entry_id}", response_model=JournalEntryRead)
def get_journal_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    entry = db.scalar(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id, JournalEntry.shop_id == user.shop_id)
        .options(
            selectinload(JournalEntry.lines).selectinload(JournalLine.account)
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return _read_entry(entry)
