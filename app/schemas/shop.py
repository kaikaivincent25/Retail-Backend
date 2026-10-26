from pydantic import BaseModel, ConfigDict, Field, field_validator

BUSINESS_TYPES = {
    "general_retail", "household_retail", "bookshop", "electronics", "clothing", "cosmetics"
}


class ShopSignup(BaseModel):
    shop_name: str = Field(..., min_length=2, max_length=150)
    shop_location: str | None = None
    admin_full_name: str = Field(..., min_length=1, max_length=150)
    admin_username: str = Field(..., min_length=3, max_length=50)
    admin_password: str = Field(..., min_length=6, max_length=100)
    business_type: str = "household_retail"

    @field_validator("business_type")
    @classmethod
    def validate_business_type(cls, value):
        if value not in BUSINESS_TYPES:
            raise ValueError("Unsupported business type")
        return value


class ShopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    location: str | None
    currency: str
    business_type: str
    mpesa_pochi_number: str | None
    mpesa_till_number: str | None
    mpesa_paybill_number: str | None
    mpesa_paybill_account_number: str | None


class ShopReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    location: str | None
    business_type: str


class PaymentDestinationRead(BaseModel):
    method: str
    label: str
    number: str
    account_number: str | None = None


class ShopUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    location: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    business_type: str | None = None
    mpesa_pochi_number: str | None = Field(default=None, max_length=50)
    mpesa_till_number: str | None = Field(default=None, max_length=50)
    mpesa_paybill_number: str | None = Field(default=None, max_length=50)
    mpesa_paybill_account_number: str | None = Field(default=None, max_length=100)

    @field_validator(
        "mpesa_pochi_number",
        "mpesa_till_number",
        "mpesa_paybill_number",
        "mpesa_paybill_account_number",
        mode="before",
    )
    @classmethod
    def normalize_payment_detail(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("business_type")
    @classmethod
    def validate_business_type(cls, value):
        if value is not None and value not in BUSINESS_TYPES:
            raise ValueError("Unsupported business type")
        return value


class ShopDeleteRequest(BaseModel):
    shop_name: str = Field(..., min_length=2, max_length=150)
    current_password: str = Field(..., min_length=1, max_length=100)
