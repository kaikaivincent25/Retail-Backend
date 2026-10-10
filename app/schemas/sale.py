from datetime import datetime
from decimal import Decimal
from typing import Literal

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
        if self.payment_method != PaymentMethod.CASH:
            raise ValueError("Use the M-Pesa STK Push endpoint for M-Pesa payments")
        return self


class MpesaSaleCreate(BaseModel):
    items: list[SaleItemIn] = Field(..., min_length=1)
    phone_number: str = Field(..., min_length=9, max_length=13)

    @model_validator(mode="after")
    def no_duplicate_variants(self):
        ids = [item.variant_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each variant should appear only once — combine quantities instead")
        return self


class ManualMpesaSaleCreate(BaseModel):
    items: list[SaleItemIn] = Field(..., min_length=1)
    payment_method: PaymentMethod

    @model_validator(mode="after")
    def validate_manual_payment_method(self):
        if self.payment_method not in {
            PaymentMethod.POCHI,
            PaymentMethod.TILL,
            PaymentMethod.PAYBILL,
        }:
            raise ValueError("Choose Pochi, Buy Goods Till, or PayBill")
        ids = [item.variant_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each variant should appear only once — combine quantities instead")
        return self


class ManualPaymentConfirm(BaseModel):
    receipt_number: str = Field(..., min_length=1, max_length=30)

    @model_validator(mode="after")
    def receipt_number_not_blank(self):
        self.receipt_number = self.receipt_number.strip()
        if not self.receipt_number:
            raise ValueError("Enter the M-Pesa confirmation code")
        return self


class SaleItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variant_id: int
    variant_name: str
    quantity: int
    unit_price: Decimal
    unit_cost_at_sale: Decimal
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
    mpesa_phone_number: str | None = None
    mpesa_receipt_number: str | None = None
    payment_destination_number: str | None = None
    payment_account_number: str | None = None
    items: list[SaleItemRead]
    created_at: datetime


class MpesaReconciliationRead(BaseModel):
    outcome: Literal["completed", "failed", "pending", "voided"]
    message: str
    sale: SaleRead