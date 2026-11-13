from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.bulk_preset import BulkPresetRead
from app.schemas.variant import VariantCreate, VariantRead

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ImageUrl = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]
Brand = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


def validate_attributes(value: dict[str, str] | None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 20:
        raise ValueError("Provide no more than 20 product attributes")
    normalized: dict[str, str] = {}
    seen: set[str] = set()
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError("Product attribute names and values must be text")
        key, item = key.strip(), item.strip()
        if not key or not item or len(key) > 50 or len(item) > 200:
            raise ValueError("Attribute names must be 1–50 characters and values 1–200 characters")
        normalized_key = key.casefold()
        if normalized_key in seen:
            raise ValueError("Product attribute names must be unique")
        seen.add(normalized_key)
        normalized[key] = item
    return normalized


class ProductCreate(BaseModel):
    name: Name
    category: Category | None = None
    brand: Brand | None = None
    description: Description | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    image_url: ImageUrl | None = None
    is_public: bool = False
    public_name: Name | None = None
    public_description: Description | None = None
    public_image_url: ImageUrl | None = None
    availability_message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    variants: list[VariantCreate] = Field(default_factory=list)

    @field_validator("attributes")
    @classmethod
    def attributes_are_bounded(cls, value):
        return validate_attributes(value)


class ProductUpdate(BaseModel):
    name: Name | None = None
    category: Category | None = None
    brand: Brand | None = None
    description: Description | None = None
    attributes: dict[str, str] | None = None
    image_url: ImageUrl | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    public_name: Name | None = None
    public_description: Description | None = None
    public_image_url: ImageUrl | None = None
    availability_message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None

    @field_validator("attributes")
    @classmethod
    def attributes_are_bounded(cls, value):
        return validate_attributes(value)


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    name: str
    category: str | None
    image_url: str | None
    is_active: bool
    brand: str | None = None
    description: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    is_public: bool = False
    public_name: str | None = None
    public_description: str | None = None
    public_image_url: str | None = None
    availability_message: str | None = None


class PublicVariantRead(BaseModel):
    id: int
    name: str
    unit: str
    sale_mode: str
    selling_price: Decimal
    is_available: bool


class PublicProductRead(BaseModel):
    id: int
    name: str
    category: str | None = None
    brand: str | None = None
    description: str | None = None
    image_url: str | None = None
    availability_message: str | None = None
    variants: list[PublicVariantRead] = Field(default_factory=list)


class PublicShopRead(BaseModel):
    name: str
    slug: str
    location: str | None = None
    currency: str
    business_type: str
    products: list[PublicProductRead] = Field(default_factory=list)


class ProductWithVariantsRead(ProductRead):
    variants: list[VariantRead] = Field(default_factory=list)


class PopularVariant(BaseModel):
    variant_id: int
    variant_name: str
    product_id: int
    product_name: str
    image_url: str | None = None
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
    image_url: str | None = None
    unit: str
    sale_mode: str
    selling_price: float
    quantity_in_stock: int
    sku: str | None = None
    barcode: str | None = None
    presets: list[BulkPresetRead] = Field(default_factory=list)
