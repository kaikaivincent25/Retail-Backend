from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_platform_owner
from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.models.activity_log import ActivityLog
from app.models.billing import BillingPlan, Subscription
from app.models.platform import PlatformAuditLog, PlatformUser
from app.models.shop import Shop
from app.models.user import User
from app.schemas.auth import Token
from app.schemas.platform import (
    PlatformActivityRead,
    PlatformBillingPlanRead,
    PlatformBillingPlanUpdate,
    PlatformFeatureSettingsRead,
    PlatformFeatureSettingsUpdate,
    PlatformOverview,
    PlatformShopRead,
    PlatformUserRead,
    PlatformUserUpdate,
)
from app.models.user import UserRole
from app.services.billing import MANAGEABLE_FEATURES, PLAN_FEATURE_KEYS, current_status, utc_now

router = APIRouter(prefix="/platform", tags=["Platform"])


@router.post("/auth/login", response_model=Token)
def platform_login(
    username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)
):
    user = db.scalar(select(PlatformUser).where(PlatformUser.username == username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect platform credentials")
    return Token(
        access_token=create_access_token(str(user.id), "platform_owner", scope="platform"),
        role="platform_owner",
    )


def _platform_subscription_counts(db: Session):
    rows = db.execute(select(Shop, Subscription).outerjoin(Subscription, Subscription.shop_id == Shop.id)).all()
    states = [current_status(subscription) for _, subscription in rows if subscription is not None]
    return (
        len(rows),
        sum(not shop.is_suspended for shop, _ in rows),
        sum(state.value == "trialing" for state in states),
        sum(state.value == "active" for state in states),
        sum(state.value == "expired" for state in states),
    )


@router.get("/overview", response_model=PlatformOverview)
def overview(db: Session = Depends(get_db), _: PlatformUser = Depends(require_platform_owner)):
    total, active, trialing, paid, expired = _platform_subscription_counts(db)
    total_active_users = db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
    revenue = db.scalar(
        select(func.coalesce(func.sum(BillingPlan.monthly_price), 0))
        .select_from(Subscription)
        .join(BillingPlan, BillingPlan.id == Subscription.plan_id)
        .where(Subscription.status == "active", Subscription.service_suspended.is_(False))
    ) or 0
    new_shops = db.scalar(select(func.count(Shop.id)).where(Shop.created_at >= utc_now() - timedelta(days=30))) or 0
    recent_activity = db.scalar(select(func.count(ActivityLog.id)).where(ActivityLog.created_at >= utc_now() - timedelta(days=7))) or 0
    return PlatformOverview(
        total_shops=total,
        active_shops=active,
        trialing_shops=trialing,
        paid_shops=paid,
        expired_shops=expired,
        total_active_users=total_active_users,
        estimated_monthly_revenue=int(revenue),
        new_shops_last_30_days=int(new_shops),
        activity_events_last_7_days=int(recent_activity),
    )


@router.get("/plans", response_model=list[PlatformBillingPlanRead])
def billing_plans(
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_platform_owner),
):
    return db.scalars(select(BillingPlan).order_by(BillingPlan.monthly_price, BillingPlan.code)).all()


@router.patch("/plans/{plan_code}", response_model=PlatformBillingPlanRead)
def update_billing_plan(
    plan_code: str,
    payload: PlatformBillingPlanUpdate,
    db: Session = Depends(get_db),
    platform_user: PlatformUser = Depends(require_platform_owner),
):
    plan = db.scalar(select(BillingPlan).where(BillingPlan.code == plan_code))
    if plan is None:
        raise HTTPException(status_code=404, detail="Billing plan not found")
    if plan.code == "free" and (payload.monthly_price != 0 or payload.annual_price not in (None, 0)):
        raise HTTPException(status_code=422, detail="The Free plan must remain priced at zero")

    unknown_features = set(payload.features) - PLAN_FEATURE_KEYS
    if unknown_features:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown plan features: {', '.join(sorted(unknown_features))}",
        )

    updated_features = {
        feature: payload.features.get(feature, False)
        for feature in sorted(PLAN_FEATURE_KEYS)
    }
    changed_features = sorted(
        feature for feature in PLAN_FEATURE_KEYS
        if bool((plan.features or {}).get(feature, False)) != updated_features[feature]
    )
    previous_values = {
        "monthly_price": plan.monthly_price,
        "annual_price": plan.annual_price,
        "max_users": plan.max_users,
    }
    plan.monthly_price = payload.monthly_price
    plan.annual_price = payload.annual_price
    plan.max_users = payload.max_users
    plan.features = updated_features
    updated_values = {
        "monthly_price": plan.monthly_price,
        "annual_price": plan.annual_price,
        "max_users": plan.max_users,
    }
    changed_values = [
        f"{field}: {previous_values[field]} -> {updated_values[field]}"
        for field in previous_values
        if previous_values[field] != updated_values[field]
    ]
    if changed_features:
        changed_values.append(f"features: {', '.join(changed_features)}")
    db.add(PlatformAuditLog(
        platform_user_id=platform_user.id,
        action="billing_plan_updated",
        description=f"{plan.name} ({plan.code}): {'; '.join(changed_values) or 'no changes'}"[:255],
    ))
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/shops", response_model=list[PlatformShopRead])
def shops(db: Session = Depends(get_db), _: PlatformUser = Depends(require_platform_owner)):
    latest_activity = (
        select(User.shop_id.label("shop_id"), func.max(ActivityLog.created_at).label("last_activity_at"))
        .join(ActivityLog, ActivityLog.user_id == User.id)
        .group_by(User.shop_id)
        .subquery()
    )
    active_users = func.count(User.id).filter(User.is_active.is_(True))
    rows = db.execute(
        select(
            Shop, BillingPlan.name, Subscription,
            active_users, latest_activity.c.last_activity_at,
        )
        .outerjoin(Subscription, Subscription.shop_id == Shop.id)
        .outerjoin(BillingPlan, BillingPlan.id == Subscription.plan_id)
        .outerjoin(User, User.shop_id == Shop.id)
        .outerjoin(latest_activity, latest_activity.c.shop_id == Shop.id)
        .group_by(Shop.id, Subscription.id, BillingPlan.name, Subscription.status, Subscription.trial_ends_at, latest_activity.c.last_activity_at)
        .order_by(Shop.created_at.desc())
    ).all()
    plan_features = {
        plan.id: plan.features
        for plan in db.scalars(select(BillingPlan)).all()
    }
    return [
        PlatformShopRead(
            id=shop.id, name=shop.name, business_type=shop.business_type,
            plan=plan_name or "Unconfigured",
            subscription_status=(current_status(subscription).value if subscription is not None else "unknown"),
            trial_ends_at=subscription.trial_ends_at if subscription is not None else None,
            active_users=int(user_count or 0),
            last_activity_at=last_activity_at, is_suspended=shop.is_suspended,
            service_suspended=subscription.service_suspended if subscription is not None else False,
            features={
                key: enabled
                for key, enabled in (
                    plan_features.get(subscription.plan_id, {}).items()
                    if subscription is not None
                    else []
                )
                if key in MANAGEABLE_FEATURES
            },
            suspended_features=(
                [
                    key for key in (subscription.suspended_features or [])
                    if key in MANAGEABLE_FEATURES
                    and plan_features.get(subscription.plan_id, {}).get(key, False)
                ]
                if subscription is not None
                else []
            ),
        )
        for shop, plan_name, subscription, user_count, last_activity_at in rows
    ]


@router.patch("/shops/{shop_id}/features", response_model=PlatformFeatureSettingsRead)
def update_shop_features(
    shop_id: int,
    payload: PlatformFeatureSettingsUpdate,
    db: Session = Depends(get_db),
    platform_user: PlatformUser = Depends(require_platform_owner),
):
    row = db.execute(
        select(Subscription, BillingPlan)
        .join(BillingPlan, BillingPlan.id == Subscription.plan_id)
        .where(Subscription.shop_id == shop_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Shop subscription not found")
    subscription, plan = row
    available_features = {
        key for key, enabled in (plan.features or {}).items()
        if enabled and key in MANAGEABLE_FEATURES
    }
    requested_features = set(payload.suspended_features)
    unsupported_features = requested_features - available_features
    if unsupported_features:
        raise HTTPException(
            status_code=422,
            detail=f"Features are not enabled on this shop's plan: {', '.join(sorted(unsupported_features))}",
        )

    previous_features = set(subscription.suspended_features or [])
    subscription.suspended_features = sorted(requested_features)
    changed_features = sorted(previous_features.symmetric_difference(requested_features))
    db.add(PlatformAuditLog(
        platform_user_id=platform_user.id,
        shop_id=shop_id,
        action="shop_features_updated",
        description=(
            f"Suspended features: {', '.join(sorted(requested_features)) or 'none'}; "
            f"changed: {', '.join(changed_features) or 'none'}"
        )[:255],
    ))
    db.commit()
    return PlatformFeatureSettingsRead(
        features={
            key: enabled
            for key, enabled in (plan.features or {}).items()
            if key in MANAGEABLE_FEATURES
        },
        suspended_features=subscription.suspended_features or [],
    )


@router.get("/shops/{shop_id}/activity", response_model=list[PlatformActivityRead])
def shop_activity(
    shop_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_platform_owner),
):
    rows = db.execute(
        select(ActivityLog, Shop.name, User.username)
        .join(User, User.id == ActivityLog.user_id)
        .join(Shop, Shop.id == User.shop_id)
        .where(Shop.id == shop_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        PlatformActivityRead(
            id=entry.id, shop_id=shop_id, shop_name=shop_name, username=username,
            action=entry.action.value, description=entry.description, created_at=entry.created_at,
        )
        for entry, shop_name, username in rows
    ]


@router.get("/shops/{shop_id}/users", response_model=list[PlatformUserRead])
def shop_users(
    shop_id: int,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_platform_owner),
):
    if db.get(Shop, shop_id) is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    return db.scalars(
        select(User).where(User.shop_id == shop_id).order_by(User.full_name.asc())
    ).all()


@router.patch("/shops/{shop_id}/users/{user_id}", response_model=PlatformUserRead)
def update_shop_user(
    shop_id: int,
    user_id: int,
    payload: PlatformUserUpdate,
    db: Session = Depends(get_db),
    platform_user: PlatformUser = Depends(require_platform_owner),
):
    user = db.scalar(select(User).where(User.id == user_id, User.shop_id == shop_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found in this shop")
    if payload.is_active is False and user.role == UserRole.ADMIN:
        admin_count = db.scalar(
            select(func.count(User.id)).where(
                User.shop_id == shop_id, User.role == UserRole.ADMIN, User.is_active.is_(True)
            )
        ) or 0
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="The last active shop admin cannot be deactivated")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    description = "Updated shop user: " + ", ".join(f"{field}={value}" for field, value in changes.items())
    db.add(PlatformAuditLog(
        platform_user_id=platform_user.id,
        shop_id=shop_id,
        action="shop_user_updated",
        description=description[:255],
    ))
    db.commit()
    db.refresh(user)
    return user


@router.post("/shops/{shop_id}/suspend", status_code=204)
def suspend_shop(
    shop_id: int, db: Session = Depends(get_db), platform_user: PlatformUser = Depends(require_platform_owner)
):
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    shop.is_suspended = True
    db.add(PlatformAuditLog(platform_user_id=platform_user.id, shop_id=shop_id, action="shop_suspended", description="Shop suspended by platform owner"))
    db.commit()


@router.post("/shops/{shop_id}/reactivate", status_code=204)
def reactivate_shop(
    shop_id: int, db: Session = Depends(get_db), platform_user: PlatformUser = Depends(require_platform_owner)
):
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    shop.is_suspended = False
    db.add(PlatformAuditLog(platform_user_id=platform_user.id, shop_id=shop_id, action="shop_reactivated", description="Shop reactivated by platform owner"))
    db.commit()


@router.post("/shops/{shop_id}/suspend-services", status_code=204)
def suspend_services(
    shop_id: int,
    db: Session = Depends(get_db),
    platform_user: PlatformUser = Depends(require_platform_owner),
):
    subscription = db.scalar(select(Subscription).where(Subscription.shop_id == shop_id))
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    subscription.service_suspended = True
    db.add(PlatformAuditLog(platform_user_id=platform_user.id, shop_id=shop_id, action="services_suspended", description="Shop services suspended by platform owner"))
    db.commit()


@router.post("/shops/{shop_id}/restore-services", status_code=204)
def restore_services(
    shop_id: int,
    db: Session = Depends(get_db),
    platform_user: PlatformUser = Depends(require_platform_owner),
):
    subscription = db.scalar(select(Subscription).where(Subscription.shop_id == shop_id))
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    subscription.service_suspended = False
    db.add(PlatformAuditLog(platform_user_id=platform_user.id, shop_id=shop_id, action="services_restored", description="Shop services restored by platform owner"))
    db.commit()
