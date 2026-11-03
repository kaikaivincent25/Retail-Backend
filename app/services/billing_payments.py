import logging
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing import BillingPayment, BillingPaymentStatus, BillingPlan, Subscription, SubscriptionStatus
from app.services.mpesa import normalize_phone_number, request_stk_push_for_reference

logger = logging.getLogger(__name__)


def create_billing_payment(
    db: Session, *, shop_id: int, user_id: int, plan: BillingPlan, phone_number: str
) -> BillingPayment:
    phone = normalize_phone_number(phone_number)
    payment = BillingPayment(
        shop_id=shop_id,
        user_id=user_id,
        plan_id=plan.id,
        amount=Decimal(plan.monthly_price),
        phone_number=phone,
        status=BillingPaymentStatus.PENDING,
    )
    db.add(payment)
    db.flush()
    try:
        identifiers = request_stk_push_for_reference(
            reference=f"BILL{payment.id}",
            description=f"RIS {plan.name}",
            amount=payment.amount,
            phone_number=phone,
            callback_url=settings.MPESA_BILLING_CALLBACK_URL,
        )
    except Exception:
        db.rollback()
        raise
    payment.checkout_request_id = identifiers["checkout_request_id"]
    payment.merchant_request_id = identifiers["merchant_request_id"]
    db.commit()
    db.refresh(payment)
    return payment


def process_billing_stk_callback(db: Session, payload: dict[str, Any]) -> bool:
    try:
        callback = payload["Body"]["stkCallback"]
        checkout_request_id = str(callback["CheckoutRequestID"])
        result_code = int(callback["ResultCode"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Malformed Safaricom billing callback.") from exc

    payment = db.scalar(
        select(BillingPayment).where(BillingPayment.checkout_request_id == checkout_request_id).with_for_update()
    )
    if payment is None:
        logger.warning("No billing payment matched Daraja checkout request %s", checkout_request_id)
        return False
    if payment.status != BillingPaymentStatus.PENDING:
        return True
    if str(callback.get("MerchantRequestID")) != payment.merchant_request_id:
        logger.error("Daraja merchant request did not match billing payment %s", payment.id)
        return False

    payment.provider_result_code = str(result_code)
    if result_code != 0:
        payment.status = BillingPaymentStatus.FAILED
        db.commit()
        return True

    metadata_items = callback.get("CallbackMetadata", {}).get("Item", [])
    metadata = {
        item.get("Name"): item.get("Value")
        for item in metadata_items
        if isinstance(item, dict) and isinstance(item.get("Name"), str)
    }
    try:
        paid_amount = Decimal(str(metadata["Amount"]))
        receipt = str(metadata["MpesaReceiptNumber"]).strip()
        paid_phone = normalize_phone_number(str(metadata["PhoneNumber"]))
    except (KeyError, InvalidOperation, ValueError):
        logger.error("Successful Daraja callback lacked valid billing metadata for payment %s", payment.id)
        return False

    if paid_amount != payment.amount or paid_phone != payment.phone_number or not receipt:
        logger.error("Billing callback details did not match payment %s", payment.id)
        return False

    payment.status = BillingPaymentStatus.COMPLETED
    payment.receipt_number = receipt
    subscription = db.scalar(select(Subscription).where(Subscription.shop_id == payment.shop_id).with_for_update())
    if subscription is None:
        logger.error("No subscription found for billing payment %s", payment.id)
        return False
    from app.services.billing import utc_now

    start = utc_now()
    subscription.plan_id = payment.plan_id
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.trial_ends_at = None
    subscription.current_period_start = start
    subscription.current_period_end = start + timedelta(days=30)
    subscription.grace_period_ends_at = None
    subscription.service_suspended = False
    db.commit()
    return True
