import pytest
import httpx

from app.core.config import settings
from app.services.product_images import (
    ProductImageStorageError,
    create_signed_product_image_upload,
)


class FakeStorageResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "url": "/object/upload/sign/products-images/shops/42/products/photo.jpg?token=upload-token"
        }


def test_signed_upload_uses_a_shop_scoped_storage_path(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://shop-project.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "server-secret")
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_BUCKET", "products-images")
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return FakeStorageResponse()

    monkeypatch.setattr("app.services.product_images.httpx.post", fake_post)

    result = create_signed_product_image_upload(42, "image/jpeg")

    assert "/shops/42/products/" in calls["url"]
    assert calls["kwargs"]["headers"]["Authorization"] == "Bearer server-secret"
    assert result["upload_url"] == (
        "https://shop-project.supabase.co/storage/v1"
        "/object/upload/sign/products-images/shops/42/products/photo.jpg?token=upload-token"
    )
    assert result["image_url"].startswith(
        "https://shop-project.supabase.co/storage/v1/object/public/products-images/shops/42/products/"
    )


def test_signed_upload_rejects_unsupported_content_type(monkeypatch):
    def unexpected_post(*args, **kwargs):
        pytest.fail("Storage must not be contacted for an unsupported image type")

    monkeypatch.setattr("app.services.product_images.httpx.post", unexpected_post)

    with pytest.raises(ValueError, match="JPG, PNG, or WebP"):
        create_signed_product_image_upload(42, "image/svg+xml")


def test_new_secret_key_uses_legacy_jwt_for_storage_authorization(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://shop-project.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test-key")
    monkeypatch.setattr(
        settings,
        "SUPABASE_STORAGE_AUTH_TOKEN",
        "eyJheader.eyJpayload.signature",
    )
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_BUCKET", "products-images")
    calls = {}

    def fake_post(url, **kwargs):
        calls["headers"] = kwargs["headers"]
        return FakeStorageResponse()

    monkeypatch.setattr("app.services.product_images.httpx.post", fake_post)

    create_signed_product_image_upload(42, "image/png")

    assert calls["headers"]["apikey"] == "sb_secret_test-key"
    assert calls["headers"]["Authorization"] == "Bearer eyJheader.eyJpayload.signature"


def test_new_secret_key_requires_a_separate_storage_jwt(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://shop-project.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test-key")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_AUTH_TOKEN", "")
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_BUCKET", "products-images")

    def unexpected_post(*args, **kwargs):
        pytest.fail("Storage must not be contacted without a valid Authorization token")

    monkeypatch.setattr("app.services.product_images.httpx.post", unexpected_post)

    with pytest.raises(ProductImageStorageError, match="SUPABASE_STORAGE_AUTH_TOKEN"):
        create_signed_product_image_upload(42, "image/png")


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "backend key"),
        (404, "PRODUCT_IMAGE_BUCKET"),
    ],
)
def test_storage_http_errors_explain_common_configuration_failures(
    monkeypatch, status_code, message
):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://shop-project.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test-key")
    monkeypatch.setattr(
        settings,
        "SUPABASE_STORAGE_AUTH_TOKEN",
        "eyJheader.eyJpayload.signature",
    )
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_BUCKET", "products-images")

    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url)
        response = httpx.Response(status_code, request=request)
        raise httpx.HTTPStatusError("Storage request failed", request=request, response=response)

    monkeypatch.setattr("app.services.product_images.httpx.post", fake_post)

    with pytest.raises(ProductImageStorageError, match=message):
        create_signed_product_image_upload(42, "image/png")


def test_bad_request_includes_storage_message_without_echoing_backend_key(monkeypatch):
    service_key = "sb_secret_test-key"
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://shop-project.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", service_key)
    monkeypatch.setattr(
        settings,
        "SUPABASE_STORAGE_AUTH_TOKEN",
        "eyJheader.eyJpayload.signature",
    )
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_BUCKET", "products-images")

    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url)
        response = httpx.Response(
            400,
            request=request,
            json={"message": f"Invalid upload configuration: {service_key}"},
        )
        raise httpx.HTTPStatusError("Storage request failed", request=request, response=response)

    monkeypatch.setattr("app.services.product_images.httpx.post", fake_post)

    with pytest.raises(ProductImageStorageError) as error:
        create_signed_product_image_upload(42, "image/png")

    assert "HTTP 400" in str(error.value)
    assert "Invalid upload configuration: [redacted]" in str(error.value)
    assert service_key not in str(error.value)


def test_signed_upload_requires_server_storage_configuration(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_AUTH_TOKEN", "")

    with pytest.raises(ProductImageStorageError, match="SUPABASE_URL"):
        create_signed_product_image_upload(42, "image/png")
