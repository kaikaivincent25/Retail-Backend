import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier, require_manager
from app.core.config import settings
from app.core.database import get_db
from app.models.customer_order import CustomerOrder
from app.models.customer_payment import CustomerPayment
from app.models.product import Product
from app.models.sale import Sale, SaleItem, SaleStatus
from app.models.user import User
from app.models.variant import Variant
from app.schemas.ai import (
    BusinessAssistantRequest,
    BusinessAssistantResponse,
    ProductImportAiRequest,
    ProductImportAiResponse,
)

router = APIRouter(prefix="/ai", tags=["AI assistant"])


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
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, params={"key": settings.GEMINI_API_KEY}, json=body)
            response.raise_for_status()
            data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        return ProductImportAiResponse.model_validate(parsed)
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="The AI assistant could not return valid suggestions. Try again.") from exc


def money(value: Decimal | int | float | None) -> float:
    return round(float(value or 0), 2)


def build_shop_context(db: Session, shop_id: int) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=30)
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
    credit_sales = db.scalar(
        select(func.coalesce(func.sum(Sale.total), 0)).where(
            Sale.shop_id == shop_id, Sale.is_credit.is_(True), Sale.status == SaleStatus.COMPLETED
        )
    )
    credit_payments = db.scalar(
        select(func.coalesce(func.sum(CustomerPayment.amount), 0)).where(CustomerPayment.shop_id == shop_id)
    )
    return {
        "period": "last 30 days",
        "sales": {"transaction_count": completed_sales[0], "revenue_kes": money(completed_sales[1]), "units_sold": int(quantity_sold or 0)},
        "top_products": [{"variant": row[0], "units": int(row[1] or 0), "sales_kes": money(row[2])} for row in top_products],
        "low_stock": [{"product": row[0], "variant": row[1], "stock": int(row[2]), "reorder_level": int(row[3])} for row in low_stock],
        "online_orders_by_status": {str(row[0].value): row[1] for row in order_counts},
        "credit_summary": {"credit_sales_kes": money(credit_sales), "recorded_payments_kes": money(credit_payments)},
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
        "You are a careful retail business assistant. Answer the user's question using only the supplied shop context. "
        "Do not invent numbers, products, customers, or recommendations. If the context is insufficient, say so. "
        "Use Kenyan shillings (KSh) when discussing money. Keep the answer concise and practical. "
        "Return JSON only with an answer string and an actions array containing at most three short suggested next steps.\n\n"
        f"Shop context:\n{json.dumps(context, ensure_ascii=False)}\n\nUser question:\n{payload.question.strip()}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, params={"key": settings.GEMINI_API_KEY}, json=body)
            response.raise_for_status()
            data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return BusinessAssistantResponse.model_validate(json.loads(text))
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="The business assistant could not return a valid answer. Try again.") from exc
