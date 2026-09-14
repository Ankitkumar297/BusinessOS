from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.invoice import InvoicePage, InvoiceStatus, InvoiceView, InvoiceWrite
from app.services.invoice_service import InvoiceService
router = APIRouter(prefix='/invoices', tags=['Invoices'])
@router.get('', response_model=InvoicePage)
def list_invoices(db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission('invoices.view'))], search: str = Query('', max_length=160), status: InvoiceStatus | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)): return InvoiceService(db, ctx).list(page, page_size, search, status)
@router.post('', response_model=InvoiceView, status_code=201)
def create_invoice(payload: InvoiceWrite, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission('invoices.create'))]): return InvoiceService(db, ctx).create(payload)
@router.get('/{invoice_id}', response_model=InvoiceView)
def get_invoice(invoice_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission('invoices.view'))]): return InvoiceService(db, ctx).get(invoice_id)
