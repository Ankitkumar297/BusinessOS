from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.reports import CustomerStatus, OrderStatus, PaymentMethod, PaymentStatus, StockStatus
from app.services.report_export_service import ReportExportService

router = APIRouter(prefix="/reports", tags=["Report exports"])
ReportContext = Annotated[TenantContext, Depends(require_permission("reports.view"))]


def csv_response(content, filename: str) -> StreamingResponse:
    return StreamingResponse(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/orders/export", response_class=StreamingResponse)
def export_orders(
    db: DbSession,
    context: ReportContext,
    start_date: date | None = None,
    end_date: date | None = None,
    status: OrderStatus | None = None,
    customer_id: UUID | None = None,
    search: str = Query("", max_length=160),
) -> StreamingResponse:
    export = ReportExportService(db, context).orders(
        start_date, end_date, status, customer_id, search.strip()
    )
    return csv_response(export, "orders-report.csv")


@router.get("/payments/export", response_class=StreamingResponse)
def export_payments(
    db: DbSession,
    context: ReportContext,
    start_date: date | None = None,
    end_date: date | None = None,
    status: PaymentStatus | None = None,
    payment_method: PaymentMethod | None = None,
    order_id: UUID | None = None,
    search: str = Query("", max_length=160),
) -> StreamingResponse:
    export = ReportExportService(db, context).payments(
        start_date, end_date, status, payment_method, order_id, search.strip()
    )
    return csv_response(export, "payments-report.csv")


@router.get("/inventory/export", response_class=StreamingResponse)
def export_inventory(
    db: DbSession,
    context: ReportContext,
    status: StockStatus | None = None,
    search: str = Query("", max_length=160),
) -> StreamingResponse:
    export = ReportExportService(db, context).inventory(status, search.strip())
    return csv_response(export, "inventory-report.csv")


@router.get("/customers/export", response_class=StreamingResponse)
def export_customers(
    db: DbSession,
    context: ReportContext,
    start_date: date | None = None,
    end_date: date | None = None,
    status: CustomerStatus | None = None,
    search: str = Query("", max_length=160),
) -> StreamingResponse:
    export = ReportExportService(db, context).customers(
        start_date, end_date, status, search.strip()
    )
    return csv_response(export, "customers-report.csv")
