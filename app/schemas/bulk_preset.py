from pydantic import BaseModel, ConfigDict, Field


class BulkPresetCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=50)
    amount: int = Field(..., gt=0)


class BulkPresetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variant_id: int
    label: str
    amount: int
    price: float
    is_active: bool