from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.billing import SubscriptionStatus


class BillingPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    monthly_price: int
    annual_price: int | None
    max_users: int | None
    features: dict[str, bool]


class BillingRead(BaseModel):
    plan: BillingPlanRead
    status: SubscriptionStatus
    trial_ends_at: datetime | None
    trial_used: bool
    current_period_start: datetime
    current_period_end: datetime
    grace_period_ends_at: datetime | None
    active_users: int
    days_remaining: int


class MpesaCheckoutCreate(BaseModel):
    plan_code: str = Field(min_length=2, max_length=40)
    phone_number: str = Field(min_length=9, max_length=20)


class MpesaCheckoutRead(BaseModel):
    payment_id: int
    plan_name: str
    amount: int
    phone_number: str
    status: str
    message: str


class MpesaPaymentStatusRead(BaseModel):
    payment_id: int
    plan_name: str
    amount: int
    status: str
    receipt_number: str | None

