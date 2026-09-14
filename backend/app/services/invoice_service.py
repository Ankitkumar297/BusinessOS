from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.models import Invoice, InvoiceItem, Order, Payment
from app.repositories.identity import UserRepository
from app.repositories.invoices import InvoiceRepository
from app.schemas.invoice import InvoicePage, InvoiceView, InvoiceWrite
from app.services.audit_service import AuditService
from app.services.auth_service import permissions_for
from app.services.team_events import TeamEvent, publish_team_event

class InvoiceService:
    def __init__(self, db: Session, ctx: TenantContext): self.db, self.ctx = db, ctx
    def begin(self, permission: str):
        actor = UserRepository(self.db).by_id_with_access(self.ctx.business_id, self.ctx.user_id)
        if not actor or permission not in permissions_for(actor): raise AppError(403, 'You do not have permission to perform this action.')
    def payment_summary(self, invoice: Invoice):
        paid = self.db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.business_id == self.ctx.business_id, Payment.order_id == invoice.order_id, Payment.status == 'completed', Payment.deleted_at.is_(None))) or Decimal('0')
        remaining = invoice.grand_total - paid
        return paid, remaining, 'paid' if remaining == 0 else ('partially_paid' if paid else 'unpaid')
    def view(self, invoice: Invoice):
        paid, remaining, state = self.payment_summary(invoice)
        item_fields = ('id','product_name','product_sku','quantity','unit_price','tax_rate','line_subtotal','line_tax','line_total')
        return InvoiceView.model_validate({**{field: getattr(invoice, field) for field in InvoiceView.model_fields if field not in {'items','paid_amount','remaining_balance','payment_state'}}, 'items': [{field: getattr(item, field) for field in item_fields} for item in invoice.items], 'paid_amount': paid, 'remaining_balance': remaining, 'payment_state': state})
    def create(self, payload: InvoiceWrite):
        self.begin('invoices.create')
        order = self.db.scalar(select(Order).options(selectinload(Order.items), selectinload(Order.customer)).where(Order.id == payload.order_id, Order.business_id == self.ctx.business_id, Order.deleted_at.is_(None)).with_for_update())
        if not order: raise AppError(404, 'Order not found.')
        if order.status != 'confirmed': raise AppError(409, 'Invoices require a confirmed order.')
        if self.db.scalar(select(Invoice.id).where(Invoice.business_id == self.ctx.business_id, Invoice.order_id == order.id, Invoice.deleted_at.is_(None))): raise AppError(409, 'An invoice already exists for this order.')
        # Locking the business serializes tenant-local sequence allocation without changing Orders.
        from app.models import Business
        self.db.execute(select(Business.id).where(Business.id == self.ctx.business_id).with_for_update()).one()
        sequence = (self.db.scalar(select(func.count()).select_from(Invoice).where(Invoice.business_id == self.ctx.business_id)) or 0) + 1
        customer = order.customer
        address = ', '.join(part for part in [customer.address_line_1, customer.address_line_2, customer.city, customer.state, customer.postal_code, customer.country] if part) or None
        invoice = Invoice(business_id=self.ctx.business_id, order_id=order.id, invoice_number=f'INV-{sequence:06d}', status='issued', issued_at=datetime.now(UTC), order_number=order.order_number, customer_name=customer.display_name, customer_email=customer.email, customer_address=address, customer_tax_id=customer.tax_id, subtotal=order.subtotal, tax_total=order.tax_total, grand_total=order.grand_total)
        invoice.items = [InvoiceItem(business_id=self.ctx.business_id, product_name=item.product_name, product_sku=item.product_sku, quantity=item.quantity, unit_price=item.unit_price, tax_rate=item.tax_rate, line_subtotal=item.line_subtotal, line_tax=item.line_tax, line_total=item.line_total) for item in order.items]
        try:
            self.db.add(invoice); self.db.flush(); AuditService(self.db,self.ctx).record(action='invoice.issued',entity_type='invoice',entity_id=invoice.id,entity_display=invoice.invoice_number,changed_fields=('order_id','invoice_number','status','issued_at','items','subtotal','tax_total','grand_total')); self.db.commit()
        except IntegrityError:
            self.db.rollback(); raise AppError(409, 'An invoice already exists for this order.')
        self.db.refresh(invoice); publish_team_event(TeamEvent('invoice.issued', self.ctx.business_id, self.ctx.user_id, invoice.id)); return self.view(invoice)
    def get(self, invoice_id: UUID):
        self.begin('invoices.view'); invoice = InvoiceRepository(self.db, self.ctx.business_id).invoice(invoice_id)
        if not invoice: raise AppError(404, 'Invoice not found.')
        return self.view(invoice)
    def list(self, page: int, size: int, search: str = '', status: str | None = None):
        self.begin('invoices.view'); rows, total = InvoiceRepository(self.db, self.ctx.business_id).invoices(search, status, page, size)
        return InvoicePage(items=[self.view(row) for row in rows], total=total, page=page, page_size=size)
