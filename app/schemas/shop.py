from pydantic import BaseModel, ConfigDict, Field, field_validator


class ShopSignup(BaseModel):
    shop_name: str = Field(..., min_length=2, max_length=150)
    shop_location: str | None = None
    admin_full_name: str = Field(..., min_length=1, max_length=150)
    admin_username: str = Field(..., min_length=3, max_length=50)
    admin_password: str = Field(..., min_length=6, max_length=100)


class ShopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    location: str | None
    currency: str
    mpesa_pochi_number: str | None
    mpesa_till_number: str | None
    mpesa_paybill_number: str | None
    mpesa_paybill_account_number: str | None


class PaymentDestinationRead(BaseModel):
    method: str
    label: str
    number: str
    account_number: str | None = None


class ShopUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    location: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
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