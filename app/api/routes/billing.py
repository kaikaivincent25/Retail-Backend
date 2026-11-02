from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.billing import BillingPlan
from app.models.user import User
from app.schemas.billing import BillingPlanRead, BillingRead
from app.services.billing import current_status, get_subscription, utc_now

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.get("/plans", response_model=list[BillingPlanRead])
def list_plans(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return db.scalars(
        select(BillingPlan).where(BillingPlan.is_active.is_(True)).order_by(BillingPlan.monthly_price)
    ).all()


@router.get("", response_model=BillingRead)
def get_billing(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    subscription, plan = get_subscription(db, user.shop_id)
    now = utc_now()
    active_users = db.scalar(
        select(func.count(User.id)).where(User.shop_id == user.shop_id, User.is_active.is_(True))
    ) or 0
    period_end = subscription.trial_ends_at if subscription.status.value == "trialing" else subscription.current_period_end
    days_remaining = max(0, (period_end - now).days)
    return BillingRead(
        plan=plan,
        status=current_status(subscription, now),
        trial_ends_at=subscription.trial_ends_at,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        grace_period_ends_at=subscription.grace_period_ends_at,
        active_users=active_users,
        days_remaining=days_remaining,
    )
