from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.stock_movement import MovementType
from app.models.variant import SaleMode, Unit


class StockAdjustment(BaseModel):
    delta: int = Field(..., ge=-1_000_000_000, le=1_000_000_000, description="Signed change: positive adds stock, negative removes it")
    movement_type: MovementType = MovementType.ADJUSTMENT
    reason: str | None = Field(default=None, max_length=255)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)

    @field_validator("delta")
    @classmethod
    def nonzero_delta(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Stock change must be nonzero")
        return value


class StaffConsumptionCreate(BaseModel):
    quantity: int = Field(..., gt=0)
    reason: str | None = Field(default=None, max_length=255)


class VariantStockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    name: str
    unit: Unit
    sale_mode: SaleMode
    quantity: int
    reorder_level: int
    is_active: bool


class VariantCostRead(BaseModel):
    id: int
    cost_price: Decimal
    cost_price_is_known: bool


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variant_id: int
    movement_type: MovementType
    quantity: int
    previous_quantity: int
    new_quantity: int
    reason: str | None
    user_id: int
    created_at: datetime
    unit_cost_at_time: Decimal | None = None
