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
    missing_settings = [
        name
        for name, value in (
            ("SUPABASE_URL", supabase_url),
            ("SUPABASE_SERVICE_ROLE_KEY", service_key),
            ("PRODUCT_IMAGE_BUCKET", bucket),
        )
        if not value
    ]
    if missing_settings:
        raise ProductImageStorageError(
            "Product image storage is not configured. Set these backend settings: "
            + ", ".join(missing_settings)
            + "."
        )

    path = f"shops/{shop_id}/products/{uuid4().hex}.{IMAGE_EXTENSIONS[content_type]}"
    encoded_bucket = quote(bucket, safe="")
    encoded_path = quote(path, safe="/")
    storage_url = f"{supabase_url}/storage/v1"

    try:
        headers = {"apikey": service_key}
        if not service_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {service_key}"
        response = httpx.post(
            f"{storage_url}/object/upload/sign/{encoded_bucket}/{encoded_path}",
            headers=headers,
            json={},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        signed_path = payload.get("url") if isinstance(payload, dict) else None
        if not isinstance(signed_path, str) or not signed_path:
            raise ProductImageStorageError("Supabase Storage returned an invalid upload URL.")
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            detail = (
                f"Supabase Storage rejected the backend key (HTTP {status_code}). "
                "Check the secret key configured for this Supabase project."
            )
        elif status_code == 404:
            detail = (
                "Supabase Storage returned HTTP 404. Check that SUPABASE_URL is the "
                "project URL and PRODUCT_IMAGE_BUCKET matches an existing bucket."
            )
        elif status_code == 413:
            detail = "Supabase Storage rejected the upload request because it is too large (HTTP 413)."
        elif status_code == 429:
            detail = "Supabase Storage is receiving too many requests. Wait a moment and try again (HTTP 429)."
        else:
            detail = f"Supabase Storage rejected the upload request (HTTP {status_code})."
        raise ProductImageStorageError(detail) from exc
    except httpx.RequestError as exc:
        raise ProductImageStorageError(
            "The backend could not connect to Supabase Storage. Check the project URL and backend network access."
        ) from exc
    except httpx.HTTPError as exc:
        raise ProductImageStorageError(
            "The backend could not prepare the Supabase Storage upload."
        ) from exc
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
