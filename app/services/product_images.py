from urllib.parse import quote
from uuid import uuid4

import httpx

from app.core.config import settings


IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class ProductImageStorageError(Exception):
    pass


def create_signed_product_image_upload(shop_id: int, content_type: str) -> dict[str, str]:
    if content_type not in IMAGE_EXTENSIONS:
        raise ValueError("Choose a JPG, PNG, or WebP image.")

    supabase_url = settings.SUPABASE_URL.strip().rstrip("/")
    service_key = settings.SUPABASE_SERVICE_ROLE_KEY.strip()
    bucket = settings.PRODUCT_IMAGE_BUCKET.strip()
    if not supabase_url or not service_key or not bucket:
        raise ProductImageStorageError("Product image storage is not configured.")

    path = f"shops/{shop_id}/products/{uuid4().hex}.{IMAGE_EXTENSIONS[content_type]}"
    encoded_bucket = quote(bucket, safe="")
    encoded_path = quote(path, safe="/")
    storage_url = f"{supabase_url}/storage/v1"

    try:
        response = httpx.post(
            f"{storage_url}/object/upload/sign/{encoded_bucket}/{encoded_path}",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            },
            json={},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        signed_path = payload.get("url") if isinstance(payload, dict) else None
        if not isinstance(signed_path, str) or not signed_path:
            raise ProductImageStorageError("Supabase Storage returned an invalid upload URL.")
    except httpx.HTTPError as exc:
        raise ProductImageStorageError("Supabase Storage could not prepare the image upload.") from exc
    except ValueError as exc:
        if isinstance(exc, ProductImageStorageError):
            raise
        raise ProductImageStorageError("Supabase Storage returned an invalid response.") from exc

    upload_url = (
        signed_path
        if signed_path.startswith(("http://", "https://"))
        else f"{storage_url}/{signed_path.lstrip('/')}"
    )
    image_url = (
        f"{storage_url}/object/public/{encoded_bucket}/{encoded_path}"
    )
    return {"upload_url": upload_url, "image_url": image_url}
