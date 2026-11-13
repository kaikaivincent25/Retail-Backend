from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.customer_order import CustomerOrderStatus, OrderFulfilment, OrderPaymentMethod, OrderPaymentStatus


class CustomerOrderItemCreate(BaseModel):
    variant_id: int
    quantity: int = Field(..., ge=1, le=999)


class CustomerOrderCreate(BaseModel):
    items: list[CustomerOrderItemCreate] = Field(..., min_length=1, max_length=100)
    customer_name: str = Field(..., min_length=2, max_length=150)
    customer_phone: str = Field(..., min_length=7, max_length=30)
    fulfilment: OrderFulfilment
    payment_method: OrderPaymentMethod
    delivery_address: str | None = Field(default=None, max_length=1000)
    estate: str | None = Field(default=None, max_length=150)
    landmark: str | None = Field(default=None, max_length=255)
    delivery_instructions: str | None = Field(default=None, max_length=1000)
    preferred_delivery_time: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_checkout(self):
        if len({item.variant_id for item in self.items}) != len(self.items):
            raise ValueError("Each product variant should appear only once")
        if self.fulfilment == OrderFulfilment.DELIVERY and not (
            self.delivery_address or self.estate or self.landmark
        ):
            raise ValueError("Add a delivery address, estate, or landmark")
        if self.fulfilment == OrderFulfilment.PICKUP and self.payment_method == OrderPaymentMethod.PAY_ON_DELIVERY:
            raise ValueError("Choose pay at pickup for pickup orders")
        if self.fulfilment == OrderFulfilment.DELIVERY and self.payment_method == OrderPaymentMethod.PAY_AT_PICKUP:
            raise ValueError("Choose pay on delivery or M-Pesa for delivery orders")
        return self


class CustomerOrderStatusUpdate(BaseModel):
    status: CustomerOrderStatus
    shop_note: str | None = Field(default=None, max_length=1000)


class CustomerOrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    variant_id: int
    variant_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class CustomerOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    shop_id: int
    order_number: str
    public_token: str
    status: CustomerOrderStatus
    fulfilment: OrderFulfilment
    payment_method: OrderPaymentMethod
    customer_name: str
    customer_phone: str
    delivery_address: str | None
    estate: str | None
    landmark: str | None
    delivery_instructions: str | None
    preferred_delivery_time: str | None
    shop_note: str | None
    subtotal: Decimal
    total: Decimal
    payment_status: OrderPaymentStatus
    mpesa_receipt_number: str | None = None
    sale_id: int | None = None
    items: list[CustomerOrderItemRead]
    created_at: datetime


class PublicOrderRead(BaseModel):
    public_token: str
    order_number: str
    status: CustomerOrderStatus
    fulfilment: OrderFulfilment
    payment_method: OrderPaymentMethod
    payment_status: OrderPaymentStatus
    mpesa_receipt_number: str | None = None
    customer_name: str
    subtotal: Decimal
    total: Decimal
    items: list[CustomerOrderItemRead]
    created_at: datetime
