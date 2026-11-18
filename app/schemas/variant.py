from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.models.variant import SaleMode, Unit

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ImageUrl = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]


class VariantCreate(BaseModel):
    name: Name
    image_url: ImageUrl | None = None
    unit: Unit
    sale_mode: SaleMode = SaleMode.FIXED
    unit_quantity: int = Field(default=1, ge=1)
    selling_price: Decimal = Field(ge=0)
    cost_price: Decimal = Field(default=Decimal("0"), ge=0)
    initial_quantity: int = Field(default=0, ge=0, le=1_000_000_000)
    sku: str | None = None
    barcode: str | None = Field(default=None, max_length=64)

    @field_validator("sku", "barcode", mode="before")
    @classmethod
    def normalize_identifiers(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def bulk_unit_quantity_is_one(self):
        if self.sale_mode == SaleMode.BULK and self.unit_quantity != 1:
            raise ValueError("unit_quantity must be 1 for bulk (measured) variants")
        if self.initial_quantity > 0 and self.cost_price <= 0:
            raise ValueError("A positive unit cost is required for opening stock")
        return self


class VariantUpdate(BaseModel):
    name: Name | None = None
    image_url: ImageUrl | None = None
    selling_price: Decimal | None = Field(default=None, ge=0)
    cost_price: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None


class CostResolution(BaseModel):
    unit_cost: Decimal = Field(..., ge=0)


class VariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    name: str
    image_url: str | None = None
    unit: Unit
    sale_mode: SaleMode
    unit_quantity: int
    selling_price: Decimal
    cost_price: Decimal
    cost_price_is_known: bool = False
    sku: str | None
    barcode: str | None = None
    is_active: bool


class VariantPriceHistoryRead(BaseModel):
    id: int
    variant_id: int
    old_price: Decimal | None = None
    new_price: Decimal
    changed_by_user_id: int
    changed_by_name: str
    created_at: datetime

