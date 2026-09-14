from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.team import StrictRequest

OrderStatus = Literal["draft", "confirmed", "cancelled"]
MONEY = Decimal("0.01")


class OrderItemWrite(StrictRequest):
    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class OrderWrite(StrictRequest):
    customer_id: UUID
    order_number: str = Field(min_length=1, max_length=64)
    order_date: datetime | None = None
    notes: str | None = Field(default=None, max_length=4000)
    items: list[OrderItemWrite] = Field(min_length=1, max_length=500)

    @field_validator("order_number")
    @classmethod
    def order_number_trimmed(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank.")
        return value.upper()

    @field_validator("notes", mode="before")
    @classmethod
    def blank_notes(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class OrderItemView(StrictRequest):
    id: UUID
    product_id: UUID
    product_name: str
    product_sku: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal


class OrderView(StrictRequest):
    id: UUID
    business_id: UUID
    customer_id: UUID
    order_number: str
    status: OrderStatus
    order_date: datetime
    notes: str | None
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemView]


class OrderPage(StrictRequest):
    items: list[OrderView]
    total: int
    page: int
    page_size: int
