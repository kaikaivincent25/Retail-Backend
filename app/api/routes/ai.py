import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier, require_manager
from app.core.config import settings
from app.core.database import get_db
from app.models.cash_session import CashSession, SessionStatus
from app.models.customer import Customer
from app.models.customer_order import CustomerOrder
from app.models.customer_payment import CustomerPayment
from app.models.expense import Expense
from app.models.product import Product
from app.models.sale import Sale, SaleItem, SaleStatus
from app.models.shop import Shop
from app.models.user import User
from app.models.variant import Variant
from app.schemas.ai import (
    BusinessAssistantRequest,
    BusinessAssistantResponse,
    ProductImportAiRequest,
    ProductImportAiResponse,
)

router = APIRouter(prefix="/ai", tags=["AI assistant"])
logger = logging.getLogger(__name__)

SOFTWARE_GUIDE = (
    "This is a multi-shop retail point-of-sale and shop-management system. "
    "Staff can use the sales checkout for cash, M-Pesa, configured Pochi/till/paybill "
    "payments, and customer credit; manage products and variants, prices, barcodes, "
    "stock levels and reorder thresholds; keep customer and credit-payment records; "
    "record expenses and open/close shop-wide cash sessions with cash reconciliation; "
    "and review sales history, reports, accounting, inventory activity, and staff access. "
    "Shops can optionally publish products in a storefront and manage customer orders "
    "for pickup or delivery. In-store checkout supports offline use and later sync. "
    "Which controls are available can depend on the user's role and the shop's setup. "
    "Use the supplied live shop data only for figures explicitly included below."
)


def parse_ai_json(data: dict) -> dict:
    candidates = data.get("candidates") or []
    if not candidates:
        block_reason = data.get("promptFeedback", {}).get("blockReason")
        raise ValueError(f"Gemini returned no candidates{f' ({block_reason})' if block_reason else ''}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = next((part.get("text") for part in parts if part.get("text")), None)
    if not text:
        finish_reason = candidates[0].get("finishReason", "unknown")
        raise ValueError(f"Gemini returned no text (finish reason: {finish_reason})")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    return json.loads(cleaned)


def provider_error(exc: httpx.HTTPStatusError) -> str:
    try:
        detail = exc.response.json().get("error", {}).get("message")
    except (ValueError, json.JSONDecodeError):
        detail = None
    return f"Gemini API error ({exc.response.status_code}){f': {detail}' if detail else ''}"


async def generate_ai_json(prompt: str) -> dict:
    """Call Gemini with bounded retries and a lightweight fallback model."""
    models = [settings.GEMINI_MODEL, settings.GEMINI_FALLBACK_MODEL]
    last_error = None
    for model in dict.fromkeys(model for model in models if model):
        for attempt in range(settings.GEMINI_MAX_ATTEMPTS):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 1200,
                    "responseMimeType": "application/json",
                },
            }
            response = None
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(url, params={"key": settings.GEMINI_API_KEY}, json=body)
                    response.raise_for_status()
                    return parse_ai_json(response.json())
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in {429, 500, 502, 503, 504}:
                    raise
            except httpx.RequestError as exc:
                last_error = exc

            if attempt < settings.GEMINI_MAX_ATTEMPTS - 1:
                retry_after = response.headers.get("Retry-After") if response is not None else None
                try:
                    delay = min(float(retry_after), 8) if retry_after else min(2 ** attempt * 2, 8)
                except ValueError:
                    delay = min(2 ** attempt * 2, 8)
                await asyncio.sleep(delay)
        logger.warning("Gemini model %s remained unavailable after retries; trying fallback.", model)

    if last_error:
        raise last_error
    raise RuntimeError("No Gemini model is configured")


@router.get("/status")
def ai_status(user: User = Depends(require_manager)):
    return {"available": bool(settings.GEMINI_API_KEY), "provider": "gemini" if settings.GEMINI_API_KEY else None}


@router.post("/product-import/suggestions", response_model=ProductImportAiResponse)
async def product_import_suggestions(
    payload: ProductImportAiRequest,
    user: User = Depends(require_manager),
):
    del user  # Authentication and manager authorization are handled by Depends.
    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI is not configured. Add GEMINI_API_KEY to the backend environment.")

    prompt = (
        "You help a small retail shop clean a product import. Return JSON only. "
        "For each product, suggest improvements only when useful. Do not invent prices, stock, barcodes, or brands. "
        "Use null for no suggestion. Flag a duplicate only when the names or variants strongly indicate the same product. "
        "Keep suggestions concise and preserve the shop's likely meaning. "
        "Return an object with a suggestions array. Each item must contain: product_name, suggested_name, "
        "suggested_category, suggested_description, duplicate_with, confidence (0 to 1), and reason.\n\n"
        f"Products:\n{json.dumps(payload.model_dump(), ensure_ascii=False)}"
    )
    try:
        parsed = await generate_ai_json(prompt)
        return ProductImportAiResponse.model_validate(parsed)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=provider_error(exc)) from exc
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        logger.exception("Gemini product-import response could not be parsed")
        raise HTTPException(status_code=502, detail=f"AI returned an unreadable response: {exc}") from exc


def money(value: Decimal | int | float | None) -> float:
    return round(float(value or 0), 2)


def build_shop_context(db: Session, shop_id: int) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    shop = db.get(Shop, shop_id)
    catalog = db.execute(
        select(
            func.count(func.distinct(Product.id)),
            func.count(func.distinct(Variant.id)),
            func.coalesce(func.sum(Variant.quantity), 0),
            func.count(func.distinct(Product.category)),
        )
        .outerjoin(
            Variant,
            (Variant.product_id == Product.id) & Variant.is_active.is_(True),
        )
        .where(Product.shop_id == shop_id, Product.is_active.is_(True))
    ).one()
    completed_sales = db.execute(
        select(func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0))
        .where(Sale.shop_id == shop_id, Sale.status == SaleStatus.COMPLETED, Sale.created_at >= since)
    ).one()
    quantity_sold = db.scalar(
        select(func.coalesce(func.sum(SaleItem.quantity), 0))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.shop_id == shop_id, Sale.status == SaleStatus.COMPLETED, Sale.created_at >= since)
    )
    top_products = db.execute(
        select(SaleItem.variant_name, func.sum(SaleItem.quantity), func.sum(SaleItem.line_total))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.shop_id == shop_id, Sale.status == SaleStatus.COMPLETED, Sale.created_at >= since)
        .group_by(SaleItem.variant_name)
        .order_by(desc(func.sum(SaleItem.quantity)))
        .limit(10)
    ).all()
    payment_totals = db.execute(
        select(Sale.payment_method, func.count(Sale.id), func.sum(Sale.total))
        .where(Sale.shop_id == shop_id, Sale.status == SaleStatus.COMPLETED, Sale.created_at >= since)
        .group_by(Sale.payment_method)
    ).all()
    low_stock = db.execute(
        select(Product.name, Variant.name, Variant.quantity, Variant.reorder_level)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Product.shop_id == shop_id,
            Product.is_active.is_(True),
            Variant.is_active.is_(True),
            Variant.quantity <= Variant.reorder_level,
        )
        .order_by(Variant.quantity)
        .limit(20)
    ).all()
    order_counts = db.execute(
        select(CustomerOrder.status, func.count(CustomerOrder.id))
        .where(CustomerOrder.shop_id == shop_id)
        .group_by(CustomerOrder.status)
    ).all()
    active_customers = db.scalar(
        select(func.count(Customer.id)).where(
            Customer.shop_id == shop_id, Customer.is_active.is_(True)
        )
    )
    expense_totals = db.execute(
        select(Expense.category, func.sum(Expense.amount))
        .join(User, User.id == Expense.user_id)
        .where(User.shop_id == shop_id, Expense.created_at >= since)
        .group_by(Expense.category)
        .order_by(desc(func.sum(Expense.amount)))
        .limit(10)
    ).all()
    credit_sales = db.scalar(
        select(func.coalesce(func.sum(Sale.total), 0)).where(
            Sale.shop_id == shop_id, Sale.is_credit.is_(True), Sale.status == SaleStatus.COMPLETED
        )
    )
    credit_payments = db.scalar(
        select(func.coalesce(func.sum(CustomerPayment.amount), 0)).where(CustomerPayment.shop_id == shop_id)
    )
    open_cash_session = db.execute(
        select(CashSession).where(
            CashSession.shop_id == shop_id,
            CashSession.status == SessionStatus.OPEN,
        )
    ).scalar_one_or_none()
    return {
        "shop_profile": {
            "name": shop.name,
            "business_type": shop.business_type,
            "currency": shop.currency,
        },
        "catalog": {
            "active_products": int(catalog[0] or 0),
            "active_variants": int(catalog[1] or 0),
            "units_in_stock": int(catalog[2] or 0),
            "categories_in_use": int(catalog[3] or 0),
            "active_customers": int(active_customers or 0),
        },
        "sales_period": "last 30 days",
        "sales": {"transaction_count": completed_sales[0], "revenue": money(completed_sales[1]), "units_sold": int(quantity_sold or 0)},
        "top_products": [{"variant": row[0], "units": int(row[1] or 0), "sales": money(row[2])} for row in top_products],
        "sales_by_payment_method": {
            row[0].value: {"transaction_count": int(row[1]), "sales": money(row[2])}
            for row in payment_totals
        },
        "low_stock": [{"product": row[0], "variant": row[1], "stock": int(row[2]), "reorder_level": int(row[3])} for row in low_stock],
        "online_orders_all_time_by_status": {str(row[0].value): row[1] for row in order_counts},
        "expenses_last_30_days_by_category": {
            str(row[0]): money(row[1]) for row in expense_totals
        },
        "open_cash_session": (
            {
                "opening_cash": money(open_cash_session.opening_cash),
                "cash_sales": (
                    money(open_cash_session.cash_sales_total)
                    if open_cash_session.cash_sales_total is not None
                    else None
                ),
                "cash_collections": (
                    money(open_cash_session.cash_collections_total)
                    if open_cash_session.cash_collections_total is not None
                    else None
                ),
                "cash_expenses": (
                    money(open_cash_session.cash_expenses_total)
                    if open_cash_session.cash_expenses_total is not None
                    else None
                ),
                "expected_cash": (
                    money(open_cash_session.expected_cash)
                    if open_cash_session.expected_cash is not None
                    else None
                ),
            }
            if open_cash_session
            else None
        ),
        "credit_summary_all_time": {
            "credit_sales": money(credit_sales),
            "recorded_payments": money(credit_payments),
            "note": "These are all-time totals, not an invoice-level outstanding balance.",
        },
    }


@router.post("/business-assistant", response_model=BusinessAssistantResponse)
async def business_assistant(
    payload: BusinessAssistantRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI is not configured. Add GEMINI_API_KEY to the backend environment.")

    context = build_shop_context(db, user.shop_id)
    prompt = (
        "You are a careful assistant for the retail shop-management software described below. "
        "Use the software guide to answer general questions about what the application does or how "
        "its workflows fit together. Use shop context only for shop-specific facts and metrics. "
        "Do not invent numbers, products, customers, features, or recommendations. If the supplied "
        "context is insufficient, say what is missing. Respect metric periods and distinguish "
        "all-time totals from current balances. Use KSh for KES amounts and otherwise use the "
        "configured shop currency. Keep the answer concise and practical. "
        "Return JSON only with an answer string and an actions array containing at most three short suggested next steps.\n\n"
        f"Software guide:\n{SOFTWARE_GUIDE}\n\n"
        f"Shop context:\n{json.dumps(context, ensure_ascii=False)}\n\nUser question:\n{payload.question.strip()}"
    )
    try:
        return BusinessAssistantResponse.model_validate(await generate_ai_json(prompt))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=provider_error(exc)) from exc
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        logger.exception("Gemini business-assistant response could not be parsed")
        raise HTTPException(status_code=502, detail=f"AI returned an unreadable response: {exc}") from exc
