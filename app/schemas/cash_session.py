from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.cash_deposit import DepositFrequency
from app.models.cash_session import SessionStatus


class SessionOpen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pass


class SessionClose(BaseModel):
    closing_cash: Decimal = Field(..., ge=Decimal("0"))


class CashSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    user_id: int
    opening_cash: Decimal
    closing_cash: Decimal | None
    expected_cash: Decimal | None
    difference: Decimal | None
    status: SessionStatus
    created_at: datetime
    closed_at: datetime | None


class CashDepositCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(..., gt=Decimal("0"))
    frequency: DepositFrequency


class CashDepositRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    session_id: int
    user_id: int
    user_name: str
    amount: Decimal
    frequency: DepositFrequency
    created_at: datetime


class CashDepositSummary(BaseModel):
    available_cash: Decimal
    deposits: list[CashDepositRead]