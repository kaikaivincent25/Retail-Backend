from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

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
    lead_status: Literal["new", "contacted", "interested", "won", "lost"] | None = None

    @field_validator("phone", "email", mode="before")
    @classmethod
    def blank_contact_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("lead_status")
    @classmethod
    def lead_status_cannot_be_cleared(cls, value):
        if value is None:
            raise ValueError("Customer lead status cannot be empty")
        return value


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    full_name: str
    phone: str | None
    email: str | None
    notes: str | None
    lead_status: str
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


class CustomerActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_type: Literal["note", "follow_up"]
    body: str = Field(..., min_length=1, max_length=2000)
    due_at: datetime | None = None
    assigned_to_user_id: int | None = Field(default=None, gt=0)

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Activity details cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_activity(self):
        if self.activity_type == "follow_up" and self.due_at is None:
            raise ValueError("Choose a due date for a follow-up")
        if self.activity_type == "note" and self.due_at is not None:
            raise ValueError("Notes cannot have a follow-up due date")
        return self


class CustomerActivityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "completed"] | None = None
    assigned_to_user_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_update(self):
        if not self.model_fields_set:
            raise ValueError("Provide a follow-up status or assignee")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Follow-up status cannot be empty")
        if "assigned_to_user_id" in self.model_fields_set and self.assigned_to_user_id is None:
            raise ValueError("Choose an active staff member")
        return self


class CustomerActivityRead(BaseModel):
    id: int
    activity_type: str
    body: str
    status: str
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    created_by_user_id: int
    created_by_name: str | None
    assigned_to_user_id: int | None
    assigned_to_name: str | None


class CustomerTimelineEntry(BaseModel):
    id: str
    kind: str
    occurred_at: datetime
    title: str
    details: str
    status: str | None = None
    amount: Decimal | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    assigned_to_name: str | None = None


class CustomerTimelineRead(BaseModel):
    customer: CustomerRead
    entries: list[CustomerTimelineEntry]


class CustomerFollowUpRead(BaseModel):
    id: int
    customer: CustomerRead
    body: str
    due_at: datetime
    status: str
    assigned_to_user_id: int | None
    assigned_to_name: str | None
    created_at: datetime


class CustomerFollowUpAssigneeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
