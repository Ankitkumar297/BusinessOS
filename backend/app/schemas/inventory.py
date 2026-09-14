from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator
from app.schemas.team import StrictRequest
Operation = Literal["opening_balance", "increase", "decrease", "correction"]
class Adjustment(StrictRequest):
    operation: Operation
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    reason: str = Field(min_length=2, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    @field_validator("reason")
    @classmethod
    def trim(cls, value: str) -> str: return value.strip()
class MovementView(StrictRequest):
    id: UUID; movement_type: str; quantity_delta: Decimal; quantity_before: Decimal; quantity_after: Decimal; reason: str; notes: str | None; created_at: datetime
class InventoryView(StrictRequest):
    id: UUID; product_id: UUID; product_name: str; sku: str; unit_of_measure: str; quantity_on_hand: Decimal; reorder_level: Decimal | None; stock_status: str; updated_at: datetime
class InventoryPage(StrictRequest):
    items: list[InventoryView]; total: int; page: int; page_size: int
