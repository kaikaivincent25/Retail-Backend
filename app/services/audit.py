from sqlalchemy.orm import Session

from app.models.activity_log import HIGH_RISK_ACTIONS, ActivityAction, ActivityLog


def log_activity(
    db: Session,
    user_id: int,
    action: ActivityAction,
    entity_type: str | None = None,
    entity_id: int | None = None,
    description: str | None = None,
) -> ActivityLog:
    """Does not commit — caller decides the transaction boundary, same pattern as apply_stock_change."""
    entry = ActivityLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        is_high_risk=action in HIGH_RISK_ACTIONS,
    )
    db.add(entry)
    return entry