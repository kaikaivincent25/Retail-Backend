from pydantic import BaseModel, Field


class ProductImportAiProduct(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    category: str | None = None
    brand: str | None = None
    description: str | None = None
    variant_names: list[str] = Field(default_factory=list)


class ProductImportAiRequest(BaseModel):
    products: list[ProductImportAiProduct] = Field(min_length=1, max_length=100)


class ProductImportAiSuggestion(BaseModel):
    product_name: str
    suggested_name: str | None = None
    suggested_category: str | None = None
    suggested_description: str | None = None
    duplicate_with: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    reason: str = ""


class ProductImportAiResponse(BaseModel):
    suggestions: list[ProductImportAiSuggestion] = Field(default_factory=list)
