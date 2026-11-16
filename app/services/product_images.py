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
    storage_auth_token = settings.SUPABASE_STORAGE_AUTH_TOKEN.strip()
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

    if service_key.startswith("sb_secret_"):
        jwt_parts = storage_auth_token.split(".")
        if len(jwt_parts) != 3 or not all(jwt_parts):
            raise ProductImageStorageError(
                "Supabase Storage needs a compact JWT in its Authorization header. "
                "Set SUPABASE_STORAGE_AUTH_TOKEN to the legacy service_role JWT, "
                "or use that JWT for SUPABASE_SERVICE_ROLE_KEY."
            )
    elif not storage_auth_token:
        storage_auth_token = service_key

    path = f"shops/{shop_id}/products/{uuid4().hex}.{IMAGE_EXTENSIONS[content_type]}"
    encoded_bucket = quote(bucket, safe="")
    encoded_path = quote(path, safe="/")
    storage_url = f"{supabase_url}/storage/v1"

    try:
        headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {storage_auth_token}",
        }
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
        elif status_code == 400:
            detail = "Supabase Storage rejected the upload request (HTTP 400)."
            try:
                payload = exc.response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("message"), str):
                provider_message = " ".join(payload["message"].split())
                provider_message = provider_message.replace(service_key, "[redacted]")
                if "related resource does not exist" in provider_message.lower():
                    detail = (
                        "Supabase Storage could not find the requested bucket. Verify that "
                        "PRODUCT_IMAGE_BUCKET exactly matches a bucket in the project identified "
                        "by SUPABASE_URL."
                    )
                elif "signature verification failed" in provider_message.lower():
                    auth_setting = (
                        "SUPABASE_STORAGE_AUTH_TOKEN"
                        if service_key.startswith("sb_secret_")
                        else "SUPABASE_SERVICE_ROLE_KEY"
                    )
                    detail = (
                        "Supabase could not verify the Storage Authorization JWT. Confirm that "
                        f"{auth_setting} is the current legacy service_role JWT from the same "
                        "project as SUPABASE_URL. If the project's JWT signing secret was rotated, "
                        "retrieve the current service_role key from Supabase API Keys settings."
                    )
                elif provider_message:
                    detail += f" Supabase says: {provider_message[:200]}"
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
