from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.sale import PaymentMethod

CustomerName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
CustomerPhone = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)
]
CustomerEmail = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=254)
]


class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: CustomerName
    phone: CustomerPhone | None = None
    email: CustomerEmail | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("phone", "email", mode="before")
    @classmethod
    def blank_contact_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class CustomerUpdate(BaseModel):
    full_name: CustomerName | None = None
    phone: CustomerPhone | None = None
    email: CustomerEmail | None = None
    notes: str | None = Field(default=None, max_length=2000)
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    is_active: bool | None = None

    @field_validator("phone", "email", mode="before")
    @classmethod
    def blank_contact_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    full_name: str
    phone: str | None
    email: str | None
    notes: str | None
    credit_limit: Decimal | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sale_id: int
    amount: Decimal = Field(..., gt=0, max_digits=10, decimal_places=2)
    payment_method: PaymentMethod = PaymentMethod.CASH
    reference: str | None = Field(default=None, max_length=100)


class CustomerPaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    customer_id: int
    sale_id: int
    session_id: int | None
    amount: Decimal
    payment_method: PaymentMethod
    reference: str | None
    recorded_by_user_id: int
    recorded_by_name: str | None = None
    created_at: datetime


class CustomerInvoiceRead(BaseModel):
    id: int
    sale_id: int
    created_at: datetime
    due_date: date | None
    total: Decimal
    amount_paid: Decimal
    balance: Decimal
    status: str


class CustomerLedgerRead(BaseModel):
    customer: CustomerRead
    total_credit_sales: Decimal
    total_payments: Decimal
    outstanding_balance: Decimal
    overdue_balance: Decimal
    invoices: list[CustomerInvoiceRead]
    payments: list[CustomerPaymentRead]
