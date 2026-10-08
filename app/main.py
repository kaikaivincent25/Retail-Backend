import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.on_event("startup")
def startup() -> None:
    try:
        run_database_migrations()
    except Exception:
        logger.exception("Database migration failed during startup")
        raise


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", 
                   "http://127.0.0.1:5173",
                   "https://retailshop-information-system.vercel.app"
                   ],
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