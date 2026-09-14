from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.repositories.customer_statements import CustomerStatementRepository
from app.schemas.customer_statement import CustomerStatement
from app.services.report_service import ReportService

MONEY = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: object) -> Decimal:
    return Decimal(str(value or ZERO)).quantize(MONEY)


class CustomerStatementService:
    def __init__(self, db: Session, context: TenantContext) -> None:
        self.db = db
        self.context = context
        self.repository = CustomerStatementRepository(db, context.business_id)

    def statement(
        self,
        customer_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> CustomerStatement:
        start, end = ReportService.date_bounds(start_date, end_date)
        customer = self.repository.customer(customer_id)
        if not customer:
            raise AppError(404, "Customer not found.")

        opening = money(self.repository.opening_balance(customer_id, start))
        result = self.repository.entries(customer_id, start, end, opening, page, page_size)
        debits = money(result["period_debits"])
        credits = money(result["period_credits"])
        rows = result["rows"]
        return CustomerStatement.model_validate(
            {
                "customer": {
                    "id": customer.id,
                    "name": customer.display_name,
                    "company": customer.company_name,
                    "email": customer.email,
                },
                "statement": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "opening_balance": opening,
                    "period_debits": debits,
                    "period_credits": credits,
                    "closing_balance": money(opening + debits - credits),
                    "pending_payment_total": money(
                        self.repository.pending_total(customer_id, start, end)
                    ),
                },
                "entries": [
                    {
                        "type": row["entry_type"],
                        "effective_at": row["effective_at"],
                        "order_id": row["order_id"],
                        "order_number": row["order_number"],
                        "invoice_id": row["invoice_id"],
                        "invoice_number": row["invoice_number"],
                        "payment_id": row["payment_id"],
                        "payment_number": row["payment_number"],
                        "payment_method": row["payment_method"],
                        "debit": money(row["debit"]),
                        "credit": money(row["credit"]),
                        "running_balance": money(row["running_balance"]),
                    }
                    for row in rows
                ],
                "total": result["total"],
                "page": page,
                "page_size": page_size,
            }
        )
