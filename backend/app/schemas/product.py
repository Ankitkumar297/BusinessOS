from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.team import StrictRequest

ProductStatus = Literal["active", "inactive"]


class ProductWrite(StrictRequest):
    name: str = Field(min_length=2, max_length=160)
    sku: str = Field(min_length=1, max_length=64)
    barcode: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    unit_of_measure: str = Field(default="piece", min_length=1, max_length=32)
    selling_price: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    cost_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    track_inventory: bool = True
    reorder_level: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("name", "sku", "unit_of_measure")
    @classmethod
    def required_trimmed(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank.")
        return value

    @field_validator("barcode", "description", "category", "brand", "notes", mode="before")
    @classmethod
    def empty_is_null(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("sku", "barcode")
    @classmethod
    def normalized_identifiers(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class ProductSupplierWrite(StrictRequest):
    supplier_id: UUID
    supplier_sku: str | None = Field(default=None, max_length=64)
    purchase_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    minimum_order_quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    is_primary: bool = False

    @field_validator("supplier_sku", mode="before")
    @classmethod
    def blank_supplier_sku(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class ProductSupplierView(ProductSupplierWrite):
    id: UUID
    product_id: UUID
    business_id: UUID
    supplier_name: str
    supplier_status: str
    created_at: datetime
    updated_at: datetime


class ProductView(ProductWrite):
    id: UUID
    business_id: UUID
    status: ProductStatus
    created_at: datetime
    updated_at: datetime
    suppliers: list[ProductSupplierView] = Field(default_factory=list)


class ProductPage(StrictRequest):
    items: list[ProductView]
    total: int
    page: int
    page_size: int
