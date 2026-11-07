from decimal import Decimal
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

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
