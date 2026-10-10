import base64
import enum
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.activity_log import ActivityAction
from app.models.sale import PaymentMethod, Sale, SaleStatus
from app.services.audit import log_activity
from app.services.sales import release_pending_sale

logger = logging.getLogger(__name__)


class MpesaConfigurationError(Exception):
    pass


class MpesaRequestError(Exception):
    def __init__(self, message: str, *, definitive_rejection: bool = False):
        super().__init__(message)
        self.definitive_rejection = definitive_rejection


class StkQueryStatus(str, enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"


def normalize_phone_number(phone_number: str) -> str:
    if not re.fullmatch(r"[+\d\s()-]+", phone_number.strip()):
        raise ValueError("Enter a valid Kenyan M-Pesa number, such as 0712345678.")
    digits = re.sub(r"\D", "", phone_number)
    if digits.startswith("0") and len(digits) == 10:
        digits = f"254{digits[1:]}"
    elif len(digits) == 9 and digits.startswith(("7", "1")):
        digits = f"254{digits}"
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise ValueError("Enter a valid Kenyan M-Pesa number, such as 0712345678.")
    return digits


def _required_settings() -> tuple[str, str, str, str, str]:
    values = (
        settings.MPESA_CONSUMER_KEY,
        settings.MPESA_CONSUMER_SECRET,
        settings.MPESA_SHORTCODE,
        settings.MPESA_PASSKEY,
        settings.MPESA_CALLBACK_URL,
    )
    if any(not value.strip() for value in values):
        raise MpesaConfigurationError(
            "M-Pesa is not configured. Set the required MPESA_* backend environment variables."
        )
    return values


def ensure_mpesa_configured() -> None:
    _required_settings()


def _access_token(client: httpx.Client, base_url: str, key: str, secret: str) -> str:
    try:
        response = client.get(
            f"{base_url}/oauth/v1/generate?grant_type=client_credentials",
            auth=(key, secret),
        )
        response.raise_for_status()
        token = response.json().get("access_token")
    except (httpx.HTTPError, ValueError) as exc:
        raise MpesaRequestError(
            "Could not authenticate with Safaricom Daraja.",
            definitive_rejection=True,
        ) from exc
    if not token:
        raise MpesaRequestError(
            "Safaricom Daraja did not return an access token.",
            definitive_rejection=True,
        )
    return token


def request_stk_push(sale_id: int, amount: Decimal, phone_number: str) -> dict[str, str]:
    key, secret, shortcode, passkey, callback_url = _required_settings()
    phone = normalize_phone_number(phone_number)
    base_url = settings.MPESA_BASE_URL.rstrip("/")
    timestamp = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        f"{shortcode}{passkey}{timestamp}".encode("utf-8")
    ).decode("ascii")

    try:
        with httpx.Client(timeout=30) as client:
            token = _access_token(client, base_url, key, secret)
            response = client.post(
                f"{base_url}/mpesa/stkpush/v1/processrequest",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "BusinessShortCode": shortcode,
                    "Password": password,
                    "Timestamp": timestamp,
                    "TransactionType": settings.MPESA_TRANSACTION_TYPE,
                    "Amount": int(amount),
                    "PartyA": phone,
                    "PartyB": shortcode,
                    "PhoneNumber": phone,
                    "CallBackURL": callback_url,
                    "AccountReference": f"SALE{sale_id}",
                    "TransactionDesc": f"Sale {sale_id}",
                },
            )
            response.raise_for_status()
            result = response.json()
    except MpesaRequestError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise MpesaRequestError(
            "Could not confirm whether Safaricom accepted the STK request. "
            "Check the customer phone and pending sale before retrying."
        ) from exc

    if not isinstance(result, dict):
        raise MpesaRequestError("Safaricom Daraja returned an invalid STK response.")
    if str(result.get("ResponseCode")) != "0":
        logger.warning(
            "Daraja rejected STK request for sale %s: %s",
            sale_id,
            result.get("ResponseDescription", "unknown provider response"),
        )
        raise MpesaRequestError(
            result.get("CustomerMessage")
            or result.get("ResponseDescription")
            or "Safaricom rejected the STK request.",
            definitive_rejection=True,
        )
    checkout_request_id = result.get("CheckoutRequestID")
    merchant_request_id = result.get("MerchantRequestID")
    if not checkout_request_id or not merchant_request_id:
        raise MpesaRequestError(
            "Safaricom accepted the request but did not return tracking identifiers."
        )
    return {
        "checkout_request_id": str(checkout_request_id),
        "merchant_request_id": str(merchant_request_id),
    }


def query_stk_status(checkout_request_id: str) -> StkQueryStatus:
    key, secret, shortcode, passkey, _ = _required_settings()
    base_url = settings.MPESA_BASE_URL.rstrip("/")
    timestamp = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        f"{shortcode}{passkey}{timestamp}".encode("utf-8")
    ).decode("ascii")

    try:
        with httpx.Client(timeout=30) as client:
            token = _access_token(client, base_url, key, secret)
            response = client.post(
                f"{base_url}/mpesa/stkpushquery/v1/query",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "BusinessShortCode": shortcode,
                    "Password": password,
                    "Timestamp": timestamp,
                    "CheckoutRequestID": checkout_request_id,
                },
            )
            response.raise_for_status()
            result = response.json()
    except MpesaRequestError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise MpesaRequestError(
            "Could not reconcile this payment with Safaricom Daraja."
        ) from exc

    if not isinstance(result, dict):
        raise MpesaRequestError("Safaricom Daraja returned an invalid query response.")
    if str(result.get("ResponseCode")) != "0":
        raise MpesaRequestError(
            "Safaricom Daraja did not accept the payment-status query."
        )
    returned_checkout_id = result.get("CheckoutRequestID")
    if returned_checkout_id and str(returned_checkout_id) != checkout_request_id:
        raise MpesaRequestError(
            "Safaricom Daraja returned a status for a different checkout request."
        )

    result_code = str(result.get("ResultCode", ""))
    if result_code == "0":
        return StkQueryStatus.COMPLETED
    if result_code in {"1", "1032", "2001"}:
        return StkQueryStatus.FAILED
    return StkQueryStatus.PENDING


def process_stk_callback(db: Session, payload: dict[str, Any]) -> bool:
    try:
        callback = payload["Body"]["stkCallback"]
        checkout_request_id = callback["CheckoutRequestID"]
        result_code = int(callback["ResultCode"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Malformed Safaricom STK callback.") from exc

    sale = db.scalar(
        select(Sale)
        .where(
            Sale.mpesa_checkout_request_id == str(checkout_request_id),
            Sale.payment_method == PaymentMethod.MPESA,
        )
        .options(selectinload(Sale.items))
        .with_for_update()
    )
    if sale is None:
        logger.warning("No sale matched Daraja checkout request %s", checkout_request_id)
        return False
    if sale.status != SaleStatus.PENDING:
        return True
    if str(callback.get("MerchantRequestID")) != sale.mpesa_merchant_request_id:
        logger.error("Daraja merchant request did not match pending sale %s", sale.id)
        return False

    if result_code != 0:
        release_pending_sale(db, sale.id)
        return True

    callback_metadata = callback.get("CallbackMetadata")
    items = callback_metadata.get("Item") if isinstance(callback_metadata, dict) else None
    if not isinstance(items, list):
        items = []
    metadata = {
        entry.get("Name"): entry.get("Value")
        for entry in items
        if isinstance(entry, dict) and isinstance(entry.get("Name"), str)
    }
    try:
        paid_amount = Decimal(str(metadata["Amount"]))
        receipt = str(metadata["MpesaReceiptNumber"]).strip()
        paid_phone = normalize_phone_number(str(metadata["PhoneNumber"]))
    except (KeyError, InvalidOperation, ValueError):
        logger.error(
            "Successful Daraja callback for sale %s lacked valid payment metadata",
            sale.id,
        )
        return False

    if (
        paid_amount != sale.total
        or paid_phone != sale.mpesa_phone_number
        or not receipt
    ):
        logger.error(
            "Daraja callback details did not match pending sale %s; amount/phone/receipt mismatch",
            sale.id,
        )
        return False

    sale.status = SaleStatus.COMPLETED
    sale.amount_received = paid_amount
    sale.mpesa_receipt_number = receipt
    log_activity(
        db,
        user_id=sale.cashier_id,
        action=ActivityAction.SALE_COMPLETED,
        entity_type="sale",
        entity_id=sale.id,
        description=f"M-Pesa sale #{sale.id} total {sale.total}",
    )
    db.commit()
    return True
