import json

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_manager
from app.core.config import settings
from app.models.user import User
from app.schemas.ai import ProductImportAiRequest, ProductImportAiResponse

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
