from datetime import UTC, datetime
from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.models import Customer, Order, OrderItem, Product
from app.repositories.identity import UserRepository
from app.repositories.orders import OrderRepository
from app.schemas.inventory import Adjustment
from app.schemas.order import OrderItemView, OrderPage, OrderView, OrderWrite
from app.services.audit_service import AuditService
from app.services.auth_service import permissions_for
from app.services.inventory_service import InventoryService
from app.services.team_events import TeamEvent, publish_team_event

MONEY = Decimal("0.01")


class OrderService:
    def __init__(self, db: Session, context: TenantContext) -> None:
        self.db, self.context, self.repo = db, context, OrderRepository(db, context.business_id)

    def begin(self, permission: str) -> None:
        self.repo.lock_business(); self.db.expire_all()
        actor = UserRepository(self.db).by_id_with_access(self.context.business_id, self.context.user_id)
        if not actor or not actor.is_active or permission not in permissions_for(actor):
            raise AppError(403, "You do not have permission to perform this action.")

    def order(self, order_id: UUID) -> Order:
        order = self.repo.order(order_id)
        if not order:
            raise AppError(404, "Order not found.")
        return order

    def view(self, order: Order) -> OrderView:
        return OrderView(id=order.id, business_id=order.business_id, customer_id=order.customer_id, order_number=order.order_number,
                         status=order.status, order_date=order.order_date, notes=order.notes, subtotal=order.subtotal, tax_total=order.tax_total,
                         grand_total=order.grand_total, created_at=order.created_at, updated_at=order.updated_at,
                         items=[OrderItemView(id=i.id, product_id=i.product_id, product_name=i.product_name, product_sku=i.product_sku, quantity=i.quantity,
                                              unit_price=i.unit_price, tax_rate=i.tax_rate, line_subtotal=i.line_subtotal, line_tax=i.line_tax, line_total=i.line_total) for i in order.items if i.deleted_at is None])

    def _customer(self, customer_id: UUID) -> Customer:
        customer = self.db.get(Customer, customer_id)
        if not customer or customer.business_id != self.context.business_id or customer.deleted_at is not None or customer.status != "active":
            raise AppError(404, "Customer not found.")
        return customer

    def _items(self, order: Order, payload: OrderWrite) -> None:
        seen: set[UUID] = set(); subtotal = tax_total = Decimal("0")
        for source in payload.items:
            if source.product_id in seen:
                raise AppError(422, "Each product may appear only once in an order.")
            seen.add(source.product_id)
            product = self.db.get(Product, source.product_id)
            if not product or product.business_id != self.context.business_id or product.deleted_at is not None or product.status != "active":
                raise AppError(404, "Product not found.")
            line_subtotal = (source.quantity * product.selling_price).quantize(MONEY, rounding=ROUND_HALF_UP)
            tax_rate = product.tax_rate or Decimal("0")
            line_tax = (line_subtotal * tax_rate / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
            line_total = line_subtotal + line_tax
            self.db.add(OrderItem(business_id=self.context.business_id, order_id=order.id, product_id=product.id, product_name=product.name,
                                  product_sku=product.sku, quantity=source.quantity, unit_price=product.selling_price, tax_rate=tax_rate,
                                  line_subtotal=line_subtotal, line_tax=line_tax, line_total=line_total))
            subtotal += line_subtotal; tax_total += line_tax
        order.subtotal = subtotal.quantize(MONEY); order.tax_total = tax_total.quantize(MONEY); order.grand_total = (subtotal + tax_total).quantize(MONEY)

    def _finish(self, event: str, order: Order, changed_fields: Iterable[str]) -> OrderView:
        AuditService(self.db, self.context).record(
            action=event,
            entity_type="order",
            entity_id=order.id,
            entity_display=order.order_number,
            changed_fields=changed_fields,
        )
        self.db.commit(); self.db.refresh(order); publish_team_event(TeamEvent(event, self.context.business_id, self.context.user_id, order.id)); return self.view(order)

    def list(self, **filters: object) -> OrderPage:
        rows, total = self.repo.orders(**filters)
        return OrderPage(items=[self.view(row) for row in rows], total=total, page=filters["page"], page_size=filters["size"])

    def create(self, payload: OrderWrite) -> OrderView:
        self.begin("orders.create"); self._customer(payload.customer_id)
        order = Order(business_id=self.context.business_id, customer_id=payload.customer_id, order_number=payload.order_number, order_date=payload.order_date or datetime.now(UTC), notes=payload.notes)
        self.db.add(order); self.db.flush(); self._items(order, payload); self.db.flush(); return self._finish("order.created", order, payload.model_dump().keys())

    def update(self, order_id: UUID, payload: OrderWrite) -> OrderView:
        self.begin("orders.update"); order = self.order(order_id)
        if order.status != "draft":
            raise AppError(409, "Only draft orders can be edited.")
        self._customer(payload.customer_id)
        requested_items = [(item.product_id, item.quantity) for item in payload.items]
        persisted_items = [(item.product_id, item.quantity) for item in order.items if item.deleted_at is None]
        requested_order_date = payload.order_date or order.order_date
        changed_fields = [
            field
            for field, current, requested in (
                ("customer_id", order.customer_id, payload.customer_id),
                ("order_number", order.order_number, payload.order_number),
                ("order_date", order.order_date, requested_order_date),
                ("notes", order.notes, payload.notes),
                ("items", persisted_items, requested_items),
            )
            if current != requested
        ]
        order.customer_id = payload.customer_id; order.order_number = payload.order_number; order.order_date = requested_order_date; order.notes = payload.notes
        for item in list(order.items): self.db.delete(item)
        self.db.flush(); self._items(order, payload); self.db.flush(); return self._finish("order.updated", order, changed_fields)

    def confirm(self, order_id: UUID) -> OrderView:
        self.begin("orders.confirm"); order = self.order(order_id)
        if order.status != "draft":
            raise AppError(409, "Only draft orders can be confirmed.")
        inventory = InventoryService(self.db, self.context)
        try:
            for item in order.items:
                inventory.adjust(item.product_id, Adjustment(operation="decrease", quantity=item.quantity, reason=f"Order {order.order_number} confirmed", notes=None), commit=False, permission=None)
            order.status = "confirmed"; self.db.flush(); return self._finish("order.confirmed", order, ["status"])
        except Exception:
            self.db.rollback(); raise

    def cancel(self, order_id: UUID) -> OrderView:
        self.begin("orders.cancel"); order = self.order(order_id)
        if order.status != "draft":
            raise AppError(409, "Only draft orders can be cancelled.")
        order.status = "cancelled"; self.db.flush(); return self._finish("order.cancelled", order, ["status"])
