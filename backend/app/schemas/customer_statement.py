from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.schemas.team import StrictRequest


StatementEntryType = Literal["order_charge", "payment"]
StatementPaymentMethod = Literal["cash", "card", "bank_transfer", "upi", "other"]


class CustomerStatementCustomer(StrictRequest):
    id: UUID
    name: str
    company: str | None
    email: str | None


class CustomerStatementSummary(StrictRequest):
    start_date: date | None
    end_date: date | None
    opening_balance: Decimal
    period_debits: Decimal
    period_credits: Decimal
    closing_balance: Decimal
    pending_payment_total: Decimal


class CustomerStatementEntry(StrictRequest):
    type: StatementEntryType
    effective_at: datetime
    order_id: UUID
    order_number: str
    invoice_id: UUID | None
    invoice_number: str | None
    payment_id: UUID | None
    payment_number: str | None
    payment_method: StatementPaymentMethod | None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal


class CustomerStatement(StrictRequest):
    customer: CustomerStatementCustomer
    statement: CustomerStatementSummary
    entries: list[CustomerStatementEntry]
    total: int
    page: int
    page_size: int
