from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.user import UserRole


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
    service_suspended: bool
    features: dict[str, bool]
    suspended_features: list[str]


class PlatformFeatureSettingsRead(BaseModel):
    features: dict[str, bool]
    suspended_features: list[str]


class PlatformFeatureSettingsUpdate(BaseModel):
    suspended_features: list[str]


class PlatformOverview(BaseModel):
    total_shops: int
    active_shops: int
    trialing_shops: int
    paid_shops: int
    expired_shops: int
    total_active_users: int
    estimated_monthly_revenue: int
    new_shops_last_30_days: int
    activity_events_last_7_days: int


class PlatformActivityRead(BaseModel):
    id: int
    shop_id: int
    shop_name: str
    username: str
    action: str
    description: str | None
    created_at: datetime


class PlatformUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    full_name: str
    username: str
    role: UserRole
    is_active: bool


class PlatformUserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
