"""Tenant-scoped product workflows; inventory quantities deliberately live elsewhere."""
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID
from typing import List

from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.models import Product, ProductSupplier, Supplier
from app.repositories.identity import UserRepository
from app.repositories.products import ProductRepository
from app.schemas.product import ProductPage, ProductSupplierView, ProductSupplierWrite, ProductView, ProductWrite
from app.services.audit_service import AuditService
from app.services.auth_service import permissions_for
from app.services.team_events import TeamEvent, publish_team_event


class ProductService:
    def __init__(self, db: Session, context: TenantContext) -> None:
        self.db, self.context = db, context
        self.repo = ProductRepository(db, context.business_id)

    def begin(self, permission: str) -> None:
        self.repo.lock_business()
        self.db.expire_all()
        actor = UserRepository(self.db).by_id_with_access(self.context.business_id, self.context.user_id)
        if not actor or not actor.is_active or permission not in permissions_for(actor):
            raise AppError(403, "You do not have permission to perform this action.")

    def product(self, product_id: UUID) -> Product:
        product = self.repo.product(product_id)
        if not product:
            raise AppError(404, "Product not found.")
        return product

    @staticmethod
    def link_view(link: ProductSupplier) -> ProductSupplierView:
        if not link.supplier:
            raise AppError(404, "Supplier not found.")
        return ProductSupplierView(id=link.id, product_id=link.product_id, business_id=link.business_id,
                                   supplier_id=link.supplier_id, supplier_sku=link.supplier_sku, purchase_cost=link.purchase_cost,
                                   lead_time_days=link.lead_time_days, minimum_order_quantity=link.minimum_order_quantity,
                                   is_primary=link.is_primary, supplier_name=link.supplier.supplier_name,
                                   supplier_status=link.supplier.status, created_at=link.created_at, updated_at=link.updated_at)

    def view(self, product: Product) -> ProductView:
        return ProductView(id=product.id, business_id=product.business_id, name=product.name, sku=product.sku,
                           barcode=product.barcode, description=product.description, category=product.category, brand=product.brand,
                           unit_of_measure=product.unit_of_measure, selling_price=product.selling_price, cost_price=product.cost_price,
                           tax_rate=product.tax_rate, track_inventory=product.track_inventory, reorder_level=product.reorder_level,
                           notes=product.notes, status=product.status, created_at=product.created_at, updated_at=product.updated_at,
                           suppliers=[self.link_view(link) for link in product.supplier_links if link.deleted_at is None])

    def finish(self, event: str, product: Product, changed_fields: Iterable[str]) -> None:
        AuditService(self.db, self.context).record(
            action=event,
            entity_type="product",
            entity_id=product.id,
            entity_display=product.name,
            changed_fields=changed_fields,
        )
        self.db.commit()
        publish_team_event(TeamEvent(event, self.context.business_id, self.context.user_id, product.id))

    def list(self, **filters: object) -> ProductPage:
        rows, total = self.repo.products(**filters)
        return ProductPage(items=[self.view(product) for product in rows], total=total, page=filters["page"], page_size=filters["size"])

    def create(self, payload: ProductWrite) -> ProductView:
        self.begin("products.create")
        product = Product(business_id=self.context.business_id, **payload.model_dump())
        self.db.add(product); self.db.flush(); result = self.view(product); self.finish("product.created", product, payload.model_dump().keys())
        return result

    def update(self, product_id: UUID, payload: ProductWrite) -> ProductView:
        self.begin("products.update"); product = self.product(product_id)
        values = payload.model_dump(); changed_fields = [field for field, value in values.items() if getattr(product, field) != value]
        for field, value in values.items(): setattr(product, field, value)
        self.db.flush(); result = self.view(product); self.finish("product.updated", product, changed_fields)
        return result

    def status(self, product_id: UUID, active: bool, delete: bool = False) -> ProductView:
        self.begin("products.delete" if delete else "products.deactivate"); product = self.product(product_id)
        product.status = "active" if active else "inactive"
        if delete: product.deleted_at = datetime.now(UTC)
        self.db.flush(); result = self.view(product); self.finish("product.deleted" if delete else ("product.activated" if active else "product.deactivated"), product, ["status"])
        return result

    def links(self, product_id: UUID) -> List[ProductSupplierView]:
        self.product(product_id)
        return [self.link_view(link) for link in self.repo.links(product_id)]

    def add_supplier(self, product_id: UUID, payload: ProductSupplierWrite) -> ProductSupplierView:
        self.begin("products.manage_suppliers"); product = self.product(product_id)
        supplier = self.db.get(Supplier, payload.supplier_id)
        if not supplier or supplier.business_id != self.context.business_id or supplier.deleted_at is not None:
            raise AppError(404, "Supplier not found.")
        if self.repo.link(product_id, supplier.id):
            raise AppError(409, "Supplier is already linked to this product.")
        if payload.is_primary:
            for link in self.repo.links(product_id): link.is_primary = False
        link = ProductSupplier(business_id=self.context.business_id, product_id=product_id, **payload.model_dump())
        self.db.add(link); self.db.flush(); self.db.refresh(link, ["supplier"]); result = self.link_view(link); self.finish("product.supplier_added", product, ["suppliers"])
        return result

    def remove_supplier(self, product_id: UUID, supplier_id: UUID) -> None:
        self.begin("products.manage_suppliers"); product = self.product(product_id); link = self.repo.link(product_id, supplier_id)
        if not link: raise AppError(404, "Supplier relationship not found.")
        link.deleted_at = datetime.now(UTC); self.db.flush(); self.finish("product.supplier_removed", product, ["suppliers"])
