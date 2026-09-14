from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import DbSession, TenantContext, require_permission
from app.services.invoice_document_service import InvoiceDocumentService

router = APIRouter(prefix="/invoices", tags=["Invoice documents"])


@router.get("/{invoice_id}/pdf", response_class=Response)
def download_invoice_pdf(
    invoice_id: UUID,
    db: DbSession,
    context: Annotated[TenantContext, Depends(require_permission("invoices.view"))],
) -> Response:
    document = InvoiceDocumentService(db, context).generate(invoice_id)
    return Response(
        content=document.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{document.filename}"',
            "Cache-Control": "private, no-store",
        },
    )
