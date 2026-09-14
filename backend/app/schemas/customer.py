from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.schemas.team import StrictRequest

CustomerType = Literal["individual", "business"]
CustomerStatus = Literal["active", "inactive"]


class CustomerWrite(StrictRequest):
    customer_type: CustomerType
    display_name: str = Field(min_length=2, max_length=160)
    company_name: str | None = Field(default=None, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    alternate_phone: str | None = Field(default=None, max_length=40)
    address_line_1: str | None = Field(default=None, max_length=160)
    address_line_2: str | None = Field(default=None, max_length=160)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=100)
    tax_id: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("company_name", "email", "phone", "alternate_phone", "address_line_1", "address_line_2",
                     "city", "state", "postal_code", "country", "tax_id", "notes", mode="before")
    @classmethod
    def empty_strings_are_null(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class CustomerView(CustomerWrite):
    id: UUID
    business_id: UUID
    status: CustomerStatus
    created_at: datetime
    updated_at: datetime


class CustomerPage(StrictRequest):
    items: list[CustomerView]
    total: int
    page: int
    page_size: int
