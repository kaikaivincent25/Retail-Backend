from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.bulk_preset import BulkPresetRead
from app.schemas.variant import VariantCreate, VariantRead

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ProductCreate(BaseModel):
    name: Name
    category: Category | None = None
    variants: list[VariantCreate] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    name: Name | None = None
    category: Category | None = None
    is_active: bool | None = None


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    name: str
    category: str | None
    is_active: bool


class ProductWithVariantsRead(ProductRead):
    variants: list[VariantRead] = Field(default_factory=list)


class PopularVariant(BaseModel):
    variant_id: int
    variant_name: str
    product_id: int
    product_name: str
    unit: str
    sale_mode: str
    selling_price: Decimal
    total_quantity_sold: int
    quantity_in_stock: int
    presets: list[BulkPresetRead] = Field(default_factory=list)


class VariantBrowseResult(BaseModel):
    variant_id: int
    variant_name: str
    product_id: int
    product_name: str
    unit: str
    sale_mode: str
    selling_price: float
    quantity_in_stock: int
    presets: list[BulkPresetRead] = Field(default_factory=list)