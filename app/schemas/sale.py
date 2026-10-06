from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.sale import PaymentMethod, SaleStatus


class SaleItemIn(BaseModel):
    variant_id: int
    quantity: int = Field(..., gt=0)


class SaleCreate(BaseModel):
    items: list[SaleItemIn] = Field(..., min_length=1)
    amount_received: Decimal = Field(..., ge=0)
    payment_method: PaymentMethod = PaymentMethod.CASH

    @model_validator(mode="after")
    def no_duplicate_variants(self):
        ids = [item.variant_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each variant should appear only once — combine quantities instead")
        return self


class SaleItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variant_id: int
    variant_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class SaleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    cashier_id: int
    session_id: int | None
    subtotal: Decimal
    total: Decimal
    amount_received: Decimal
    change: Decimal
    payment_method: PaymentMethod
    status: SaleStatus
    items: list[SaleItemRead]
    created_at: datetime