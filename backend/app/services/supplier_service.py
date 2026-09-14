"""Tenant-scoped supplier workflows with event-ready mutations."""
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.models import Supplier
from app.repositories.identity import UserRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.supplier import SupplierPage, SupplierView, SupplierWrite
from app.services.audit_service import AuditService
from app.services.auth_service import permissions_for
from app.services.team_events import TeamEvent, publish_team_event


class SupplierService:
    def __init__(self, db: Session, context: TenantContext) -> None:
        self.db, self.context = db, context
        self.repo = SupplierRepository(db, context.business_id)

    def begin(self, permission: str) -> None:
        self.repo.lock_business()
        self.db.expire_all()
        actor = UserRepository(self.db).by_id_with_access(self.context.business_id, self.context.user_id)
        if not actor or not actor.is_active or permission not in permissions_for(actor):
            raise AppError(403, "You do not have permission to perform this action.")

    def supplier(self, supplier_id: UUID) -> Supplier:
        supplier = self.repo.supplier(supplier_id)
        if not supplier:
            raise AppError(404, "Supplier not found.")
        return supplier

    @staticmethod
    def view(supplier: Supplier) -> SupplierView:
        return SupplierView.model_validate(supplier, from_attributes=True)

    def finish(self, event: str, supplier: Supplier, changed_fields: Iterable[str]) -> None:
        AuditService(self.db, self.context).record(
            action=event,
            entity_type="supplier",
            entity_id=supplier.id,
            entity_display=supplier.supplier_name,
            changed_fields=changed_fields,
        )
        self.db.commit()
        publish_team_event(TeamEvent(event, self.context.business_id, self.context.user_id, supplier.id))

    def list(self, search: str, status: str | None, country: str | None, sort_by: str,
             sort_direction: str, page: int, size: int) -> SupplierPage:
        rows, total = self.repo.suppliers(search, status, country, sort_by, sort_direction, page, size)
        return SupplierPage(items=[self.view(supplier) for supplier in rows], total=total, page=page, page_size=size)

    def create(self, payload: SupplierWrite) -> SupplierView:
        self.begin("suppliers.create")
        supplier = Supplier(business_id=self.context.business_id, **payload.model_dump())
        self.db.add(supplier)
        self.db.flush()
        result = self.view(supplier)
        self.finish("supplier.created", supplier, payload.model_dump().keys())
        return result

    def update(self, supplier_id: UUID, payload: SupplierWrite) -> SupplierView:
        self.begin("suppliers.update")
        supplier = self.supplier(supplier_id)
        values = payload.model_dump()
        changed_fields = [
            field for field, value in values.items() if getattr(supplier, field) != value
        ]
        for field, value in values.items():
            setattr(supplier, field, value)
        self.db.flush()
        result = self.view(supplier)
        self.finish("supplier.updated", supplier, changed_fields)
        return result

    def status(self, supplier_id: UUID, active: bool, delete: bool = False) -> SupplierView:
        self.begin("suppliers.delete" if delete else "suppliers.deactivate")
        supplier = self.supplier(supplier_id)
        supplier.status = "active" if active else "inactive"
        if delete:
            supplier.deleted_at = datetime.now(UTC)
        self.db.flush()
        result = self.view(supplier)
        self.finish(
            "supplier.deleted" if delete else ("supplier.activated" if active else "supplier.deactivated"),
            supplier,
            ["status"],
        )
        return result
