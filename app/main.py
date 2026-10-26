import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    audit,
    auth,
    cash_sessions,
    dashboard,
    expenses,
    health,
    inventory,
    products,
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
    logger.exception("Unhandled request error: %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "The backend could not complete this request. Check the Render service logs."},
    )


@app.on_event("startup")
def startup() -> None:
    try:
        run_database_migrations()
    except Exception:
        logger.exception("Database migration failed during startup")
        raise


app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip().rstrip("/") for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(audit.router)
app.include_router(inventory.router)
app.include_router(variants.router)
app.include_router(auth.router)
app.include_router(expenses.router)
app.include_router(products.router)
app.include_router(sales.router)
app.include_router(cash_sessions.router)
app.include_router(users.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(shop.router)
