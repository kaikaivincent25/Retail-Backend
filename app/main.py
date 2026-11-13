import logging
import secrets
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    audit,
    accounting,
    auth,
    billing,
    platform,
    cash_sessions,
    dashboard,
    customers,
    expenses,
    health,
    inventory,
    products,
    public_catalog,
    customer_orders,
    reports,
    sales,
    shop,
    users,
    variants,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


def run_database_migrations() -> None:
    if settings.ENVIRONMENT.lower() == "test":
        return

    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    command.upgrade(config, "head")


app = FastAPI(title=settings.APP_NAME)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    error_id = secrets.token_hex(8)
    logger.exception(
        "Unhandled request error [%s]: %s %s",
        error_id,
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected server error occurred.", "error_id": error_id},
    )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith(("/auth", "/platform/auth")):
        response.headers.setdefault("Cache-Control", "no-store")
    if settings.ENVIRONMENT.lower() in {"production", "prod"} and request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

@app.on_event("startup")
def startup() -> None:
    try:
        run_database_migrations()
    except Exception:
        logger.exception("Database migration failed during startup")
        raise


configured_origins = [
    origin.strip().rstrip("/")
    for origin in settings.CORS_ORIGINS.split(",")
    if origin.strip()
]
# Keep the deployed frontend allowed even when Render has an incomplete
# CORS_ORIGINS environment variable. Additional origins can still be supplied
# through CORS_ORIGINS for local development or other approved deployments.
origins = sorted(
    set(configured_origins)
    | {"https://retailshop-information-system.vercel.app"}
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)
app.include_router(health.router)
app.include_router(audit.router)
app.include_router(accounting.router)
app.include_router(inventory.router)
app.include_router(variants.router)
app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(platform.router)
app.include_router(expenses.router)
app.include_router(products.router)
app.include_router(public_catalog.router)
app.include_router(customer_orders.public_router)
app.include_router(customer_orders.private_router)
app.include_router(sales.router)
app.include_router(cash_sessions.router)
app.include_router(customers.router)
app.include_router(users.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(shop.router)
