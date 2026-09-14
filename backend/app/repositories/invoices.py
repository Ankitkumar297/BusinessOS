from uuid import UUID
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload
from app.models import Invoice

class InvoiceRepository:
    def __init__(self, db: Session, business_id: UUID): self.db, self.business_id = db, business_id
    def query(self) -> Select[tuple[Invoice]]:
        return select(Invoice).options(selectinload(Invoice.items)).where(Invoice.business_id == self.business_id, Invoice.deleted_at.is_(None))
    def invoice(self, invoice_id: UUID) -> Invoice | None: return self.db.scalar(self.query().where(Invoice.id == invoice_id))
    def invoices(self, search: str, status: str | None, page: int, size: int) -> tuple[list[Invoice], int]:
        query = self.query()
        if search:
            term = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            query = query.where(or_(Invoice.invoice_number.ilike(term, escape='\\'), Invoice.order_number.ilike(term, escape='\\'), Invoice.customer_name.ilike(term, escape='\\')))
        if status: query = query.where(Invoice.status == status)
        total = self.db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
        return list(self.db.scalars(query.order_by(Invoice.issued_at.desc(), Invoice.id).offset((page - 1) * size).limit(size)).unique()), total
