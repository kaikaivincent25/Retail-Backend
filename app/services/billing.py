from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.billing import BillingPlan, Subscription, SubscriptionStatus
from app.models.user import User

TRIAL_DAYS = 45


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_subscription(db: Session, shop_id: int):
    row = db.execute(
        select(Subscription, BillingPlan)
        .join(BillingPlan, BillingPlan.id == Subscription.plan_id)
        .where(Subscription.shop_id == shop_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=503, detail="Billing is not configured for this shop")
    return row[0], row[1]


def current_status(subscription: Subscription, now: datetime | None = None) -> SubscriptionStatus:
    now = now or utc_now()
    if subscription.status == SubscriptionStatus.CANCELED:
        return SubscriptionStatus.CANCELED
    if subscription.status == SubscriptionStatus.TRIALING:
        if subscription.trial_ends_at and now <= subscription.trial_ends_at:
            return SubscriptionStatus.TRIALING
        if subscription.grace_period_ends_at and now <= subscription.grace_period_ends_at:
            return SubscriptionStatus.PAST_DUE
        return SubscriptionStatus.EXPIRED
    if now <= subscription.current_period_end:
        return subscription.status
    if subscription.grace_period_ends_at and now <= subscription.grace_period_ends_at:
        return SubscriptionStatus.PAST_DUE
    return SubscriptionStatus.EXPIRED


def is_service_blocked(subscription: Subscription) -> bool:
    return subscription.service_suspended or current_status(subscription) in {
        SubscriptionStatus.EXPIRED,
        SubscriptionStatus.CANCELED,
    }


def require_feature(db: Session, shop_id: int, feature_key: str) -> None:
    subscription, plan = get_subscription(db, shop_id)
    state = current_status(subscription)
    if state in {SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELED}:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Your subscription has expired. Choose a plan to continue using this feature.",
        )
    if not plan.features.get(feature_key, False):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="This feature is not included in your current plan.",
        )


def enforce_user_limit(db: Session, shop_id: int) -> None:
    subscription, plan = get_subscription(db, shop_id)
    state = current_status(subscription)
    if state in {SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELED}:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Your subscription has expired. Choose a plan to add users.",
        )
    if plan.max_users is None:
        return
    active_users = db.scalar(
        select(func.count(User.id)).where(User.shop_id == shop_id, User.is_active.is_(True))
    ) or 0
    if active_users >= plan.max_users:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Your {plan.name} plan allows {plan.max_users} active users. Upgrade to add more.",
        )
