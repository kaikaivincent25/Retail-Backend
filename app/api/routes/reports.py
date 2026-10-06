from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_manager
from app.core.database import get_db
from app.models.user import User
from app.schemas.reporting import PeriodReport
from app.services.reporting import summarize_period

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/summary", response_model=PeriodReport)
def period_summary(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must not be before start_date")
    if (end_date - start_date) > timedelta(days=366):
        raise HTTPException(status_code=422, detail="Date range cannot exceed one year")

    result = summarize_period(db, user.shop_id, start_date, end_date)
    return PeriodReport(**result)