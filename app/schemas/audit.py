from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.activity_log import ActivityAction


class ActivityLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    action: ActivityAction
    entity_type: str | None
    entity_id: int | None
    description: str | None
    is_high_risk: bool
    created_at: datetime