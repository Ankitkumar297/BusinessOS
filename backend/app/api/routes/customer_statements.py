from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.customer_statement import CustomerStatement
from app.services.customer_statement_service import CustomerStatementService

router = APIRouter(prefix="/reports", tags=["Customer statements"])
StatementContext = Annotated[TenantContext, Depends(require_permission("reports.view"))]


@router.get("/customers/{customer_id}/statement", response_model=CustomerStatement)
def customer_statement(
    customer_id: UUID,
    db: DbSession,
    context: StatementContext,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> CustomerStatement:
    return CustomerStatementService(db, context).statement(
        customer_id, start_date, end_date, page, page_size
    )
