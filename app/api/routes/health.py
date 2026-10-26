from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/health/db")
def db_health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/health/ready")
def readiness_check(db: Session = Depends(get_db)):
    """Verify that the schema required by authentication is available."""
    db.execute(text("SELECT id FROM users LIMIT 1"))
    return {"status": "ok", "database": "ready"}
