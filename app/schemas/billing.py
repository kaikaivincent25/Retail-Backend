from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
    current_period_start: datetime
    current_period_end: datetime
    grace_period_ends_at: datetime | None
    active_users: int
    days_remaining: int

