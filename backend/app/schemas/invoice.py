from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import Field
from app.schemas.team import StrictRequest

InvoiceStatus = Literal['issued']
PaymentState = Literal['unpaid', 'partially_paid', 'paid']

class InvoiceWrite(StrictRequest):
    order_id: UUID

class InvoiceItemView(StrictRequest):
    id: UUID; product_name: str; product_sku: str; quantity: Decimal; unit_price: Decimal; tax_rate: Decimal; line_subtotal: Decimal; line_tax: Decimal; line_total: Decimal

class InvoiceView(StrictRequest):
    id: UUID; business_id: UUID; order_id: UUID; invoice_number: str; status: InvoiceStatus; issued_at: datetime
    order_number: str; customer_name: str; customer_email: str | None; customer_address: str | None; customer_tax_id: str | None
    subtotal: Decimal; tax_total: Decimal; grand_total: Decimal; paid_amount: Decimal; remaining_balance: Decimal; payment_state: PaymentState
    created_at: datetime; updated_at: datetime; items: list[InvoiceItemView]

class InvoicePage(StrictRequest):
    items: list[InvoiceView]; total: int; page: int; page_size: int
