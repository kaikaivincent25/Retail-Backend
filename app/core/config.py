from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(value: str) -> str:
    """Make PostgreSQL URLs work with the psycopg 3 driver used by this app."""
    value = value.strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    if ".supabase." in value and "sslmode=" not in value:
        value += "&sslmode=require" if "?" in value else "?sslmode=require"
    return value


class Settings(BaseSettings):
    APP_NAME: str = "Duka Retail System"
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,https://retailshop-information-system.vercel.app"
    DATABASE_URL: str
    TEST_DATABASE_URL: str = ""

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    MPESA_BASE_URL: str = "https://sandbox.safaricom.co.ke"
    MPESA_CONSUMER_KEY: str = ""
    MPESA_CONSUMER_SECRET: str = ""
    MPESA_SHORTCODE: str = ""
    MPESA_PASSKEY: str = ""
    MPESA_CALLBACK_URL: str = ""
    MPESA_TRANSACTION_TYPE: str = "CustomerPayBillOnline"

    _normalize_database_urls = field_validator("DATABASE_URL", "TEST_DATABASE_URL", mode="before")(
        normalize_database_url
    )

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
