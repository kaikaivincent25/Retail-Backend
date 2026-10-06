from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.variant import SaleMode, Unit

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class VariantCreate(BaseModel):
    name: Name
    unit: Unit
    sale_mode: SaleMode = SaleMode.FIXED
    unit_quantity: int = Field(default=1, ge=1)
    selling_price: Decimal = Field(ge=0)
    cost_price: Decimal = Field(default=Decimal("0"), ge=0)
    sku: str | None = None

    @model_validator(mode="after")
    def bulk_unit_quantity_is_one(self):
        if self.sale_mode == SaleMode.BULK and self.unit_quantity != 1:
            raise ValueError("unit_quantity must be 1 for bulk (measured) variants")
        return self


class VariantUpdate(BaseModel):
    name: Name | None = None
    selling_price: Decimal | None = Field(default=None, ge=0)
    cost_price: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None


class VariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    name: str
    unit: Unit
    sale_mode: SaleMode
    unit_quantity: int
    selling_price: Decimal
    cost_price: Decimal
    sku: str | None
    is_active: bool

