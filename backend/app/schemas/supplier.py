from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.schemas.team import StrictRequest

SupplierStatus = Literal["active", "inactive"]


class SupplierWrite(StrictRequest):
    supplier_name: str = Field(min_length=2, max_length=160)
    company_name: str | None = Field(default=None, max_length=160)
    supplier_code: str | None = Field(default=None, max_length=50)
    tax_id: str | None = Field(default=None, max_length=100)
    registration_number: str | None = Field(default=None, max_length=100)
    contact_person_name: str | None = Field(default=None, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    alternate_phone: str | None = Field(default=None, max_length=40)
    address_line_1: str | None = Field(default=None, max_length=160)
    address_line_2: str | None = Field(default=None, max_length=160)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=100)
    payment_terms: str | None = Field(default=None, max_length=100)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    minimum_order_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("company_name", "supplier_code", "tax_id", "registration_number", "contact_person_name", "email",
                     "phone", "alternate_phone", "address_line_1", "address_line_2", "city", "state", "postal_code",
                     "country", "payment_terms", "currency", "notes", mode="before")
    @classmethod
    def empty_strings_are_null(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("supplier_code", "currency")
    @classmethod
    def normalize_codes(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class SupplierView(SupplierWrite):
    id: UUID
    business_id: UUID
    status: SupplierStatus
    created_at: datetime
    updated_at: datetime


class SupplierPage(StrictRequest):
    items: list[SupplierView]
    total: int
    page: int
    page_size: int
