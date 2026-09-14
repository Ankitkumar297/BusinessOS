from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.reports import (
    CustomerReport,
    CustomerStatus,
    InventoryReport,
    OrderReport,
    OrderStatus,
    PaymentMethod,
    PaymentReport,
    PaymentStatus,
    StockStatus,
)
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["Reports"])
ReportContext = Annotated[TenantContext, Depends(require_permission("reports.view"))]


@router.get("/orders", response_model=OrderReport)
def order_report(
    db: DbSession,
    context: ReportContext,
    start_date: date | None = None,
    end_date: date | None = None,
    status: OrderStatus | None = None,
    customer_id: UUID | None = None,
    search: str = Query("", max_length=160),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> OrderReport:
    return ReportService(db, context).orders(start_date, end_date, status, customer_id, search.strip(), page, page_size)


@router.get("/payments", response_model=PaymentReport)
def payment_report(
    db: DbSession,
    context: ReportContext,
    start_date: date | None = None,
    end_date: date | None = None,
    status: PaymentStatus | None = None,
    payment_method: PaymentMethod | None = None,
    order_id: UUID | None = None,
    search: str = Query("", max_length=160),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaymentReport:
    return ReportService(db, context).payments(start_date, end_date, status, payment_method, order_id, search.strip(), page, page_size)


@router.get("/inventory", response_model=InventoryReport)
def inventory_report(
    db: DbSession,
    context: ReportContext,
    status: StockStatus | None = None,
    search: str = Query("", max_length=160),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> InventoryReport:
    return ReportService(db, context).inventory(status, search.strip(), page, page_size)


@router.get("/customers", response_model=CustomerReport)
def customer_report(
    db: DbSession,
    context: ReportContext,
    start_date: date | None = None,
    end_date: date | None = None,
    status: CustomerStatus | None = None,
    search: str = Query("", max_length=160),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> CustomerReport:
    return ReportService(db, context).customers(start_date, end_date, status, search.strip(), page, page_size)
