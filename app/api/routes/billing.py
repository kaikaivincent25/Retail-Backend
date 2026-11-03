from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_for_billing
from app.core.database import get_db
from app.models.billing import BillingPayment, BillingPlan, SubscriptionStatus
from app.models.user import User
from app.schemas.billing import BillingPlanRead, BillingRead, MpesaCheckoutCreate, MpesaCheckoutRead, MpesaPaymentStatusRead
from app.services.billing_payments import create_billing_payment, process_billing_stk_callback
from app.services.mpesa import MpesaConfigurationError, MpesaRequestError
from app.services.billing import TRIAL_DAYS, current_status, get_subscription, utc_now

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.get("/plans", response_model=list[BillingPlanRead])
def list_plans(db: Session = Depends(get_db), user: User = Depends(get_current_user_for_billing)):
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Only the shop administrator can view billing plans")
    return db.scalars(
        select(BillingPlan).where(BillingPlan.is_active.is_(True)).order_by(BillingPlan.monthly_price)
    ).all()


@router.get("", response_model=BillingRead)
def get_billing(db: Session = Depends(get_db), user: User = Depends(get_current_user_for_billing)):
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Only the shop administrator can manage billing")
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


@router.post("/start-trial", response_model=BillingRead)
def start_trial(db: Session = Depends(get_db), user: User = Depends(get_current_user_for_billing)):
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Only the shop administrator can start a trial")
    subscription, current_plan = get_subscription(db, user.shop_id)
    if current_plan.code != "free" or subscription.trial_ends_at is not None:
        raise HTTPException(status_code=409, detail="The free trial has already been used")
    business_plan = db.scalar(select(BillingPlan).where(BillingPlan.code == "business", BillingPlan.is_active.is_(True)))
    if business_plan is None:
        raise HTTPException(status_code=503, detail="Business trial plan is not configured")
    start = utc_now()
    end = start + timedelta(days=TRIAL_DAYS)
    subscription.plan_id = business_plan.id
    subscription.status = SubscriptionStatus.TRIALING
    subscription.trial_ends_at = end
    subscription.current_period_start = start
    subscription.current_period_end = end
    subscription.service_suspended = False
    db.commit()
    db.refresh(subscription)
    return get_billing(db, user)


@router.post("/mpesa/checkout", response_model=MpesaCheckoutRead, status_code=202)
def create_mpesa_checkout(
    payload: MpesaCheckoutCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_for_billing),
):
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Only the shop administrator can make billing payments")
    plan = db.scalar(select(BillingPlan).where(BillingPlan.code == payload.plan_code, BillingPlan.is_active.is_(True)))
    if plan is None or plan.code == "free":
        raise HTTPException(status_code=404, detail="Paid billing plan not found")
    if plan.monthly_price <= 0:
        raise HTTPException(status_code=422, detail="This plan cannot be paid through M-Pesa")
    try:
        payment = create_billing_payment(
            db, shop_id=user.shop_id, user_id=user.id, plan=plan, phone_number=payload.phone_number
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MpesaConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MpesaRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MpesaCheckoutRead(
        payment_id=payment.id,
        plan_name=plan.name,
        amount=plan.monthly_price,
        phone_number=payment.phone_number,
        status=payment.status.value,
        message="STK Push sent. Complete the payment on the phone, then return to Billing to refresh the status.",
    )


@router.post("/mpesa/callback")
def billing_mpesa_callback(payload: dict, db: Session = Depends(get_db)):
    try:
        processed = process_billing_stk_callback(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ResultCode": 0, "ResultDesc": "Accepted" if processed else "Callback received for reconciliation"}


@router.get("/mpesa/payments/{payment_id}", response_model=MpesaPaymentStatusRead)
def mpesa_payment_status(
    payment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_for_billing),
):
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Only the shop administrator can view billing payments")
    row = db.execute(
        select(BillingPayment, BillingPlan)
        .join(BillingPlan, BillingPlan.id == BillingPayment.plan_id)
        .where(BillingPayment.id == payment_id, BillingPayment.shop_id == user.shop_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Billing payment not found")
    payment, plan = row
    return MpesaPaymentStatusRead(
        payment_id=payment.id,
        plan_name=plan.name,
        amount=int(payment.amount),
        status=payment.status.value,
        receipt_number=payment.receipt_number,
    )
