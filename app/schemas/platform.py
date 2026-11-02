from datetime import datetime

from pydantic import BaseModel


class PlatformShopRead(BaseModel):
    id: int
    name: str
    business_type: str
    plan: str
    subscription_status: str
    trial_ends_at: datetime | None
    active_users: int
    last_activity_at: datetime | None
    is_suspended: bool


class PlatformOverview(BaseModel):
    total_shops: int
    active_shops: int
    trialing_shops: int
    paid_shops: int
    expired_shops: int
    total_active_users: int


class PlatformActivityRead(BaseModel):
    id: int
    shop_id: int
    shop_name: str
    username: str
    action: str
    description: str | None
    created_at: datetime
