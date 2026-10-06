from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class ExpenseCreate(BaseModel):
    category: Category
    description: str | None = Field(default=None, max_length=255)
    amount: Decimal = Field(..., gt=0)


class ExpenseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    session_id: int | None
    category: str
    description: str | None
    amount: Decimal
    created_at: datetime
    user_name: str | None = None