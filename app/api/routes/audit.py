from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_manager
from app.core.database import get_db
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.schemas.audit import ActivityLogRead

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("", response_model=list[ActivityLogRead])
def list_activity(
    high_risk_only: bool = False,
    user_id: int | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    query = select(ActivityLog).join(User, User.id == ActivityLog.user_id).where(
        User.shop_id == user.shop_id
    )
    if high_risk_only:
        query = query.where(ActivityLog.is_high_risk.is_(True))
    if user_id is not None:
        query = query.where(ActivityLog.user_id == user_id)

    query = query.order_by(ActivityLog.created_at.desc()).offset(skip).limit(limit)
    return db.scalars(query).all()