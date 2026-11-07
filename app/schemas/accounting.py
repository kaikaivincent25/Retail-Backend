from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    account_type: str
    is_system: bool
    is_active: bool


class JournalLineRead(BaseModel):
    id: int
    account_code: str
    account_name: str
    account_type: str
    debit: Decimal
    credit: Decimal
    description: str | None


class JournalEntryRead(BaseModel):
    id: int
    entry_date: date
    currency: str
    source_type: str
    source_id: int
    description: str
    created_by_user_id: int
    created_at: datetime
    debit_total: Decimal
    credit_total: Decimal
    lines: list[JournalLineRead]
