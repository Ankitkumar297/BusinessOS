"""Tenant-scoped customer workflows and post-commit domain events."""
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.models import Customer
from app.repositories.customers import CustomerRepository
from app.repositories.identity import UserRepository
from app.schemas.customer import CustomerPage, CustomerView, CustomerWrite
from app.services.audit_service import AuditService
from app.services.auth_service import permissions_for
from app.services.team_events import TeamEvent, publish_team_event


class CustomerService:
    def __init__(self, db: Session, context: TenantContext) -> None:
        self.db, self.context = db, context
        self.repo = CustomerRepository(db, context.business_id)

    def begin(self, permission: str) -> None:
        self.repo.lock_business()
        self.db.expire_all()
        actor = UserRepository(self.db).by_id_with_access(self.context.business_id, self.context.user_id)
        if not actor or not actor.is_active or permission not in permissions_for(actor):
            raise AppError(403, "You do not have permission to perform this action.")

    def customer(self, customer_id: UUID) -> Customer:
        customer = self.repo.customer(customer_id)
        if not customer:
            raise AppError(404, "Customer not found.")
        return customer

    @staticmethod
    def view(customer: Customer) -> CustomerView:
        return CustomerView.model_validate(customer, from_attributes=True)

    def finish(self, event: str, customer: Customer, changed_fields: Iterable[str]) -> None:
        AuditService(self.db, self.context).record(
            action=event,
            entity_type="customer",
            entity_id=customer.id,
            entity_display=customer.display_name,
            changed_fields=changed_fields,
        )
        self.db.commit()
        publish_team_event(TeamEvent(event, self.context.business_id, self.context.user_id, customer.id))

    def list(self, search: str, status: str | None, customer_type: str | None, sort_by: str,
             sort_direction: str, page: int, size: int) -> CustomerPage:
        rows, total = self.repo.customers(search, status, customer_type, sort_by, sort_direction, page, size)
        return CustomerPage(items=[self.view(customer) for customer in rows], total=total, page=page, page_size=size)

    def create(self, payload: CustomerWrite) -> CustomerView:
        self.begin("customers.create")
        customer = Customer(business_id=self.context.business_id, **payload.model_dump())
        self.db.add(customer)
        self.db.flush()
        result = self.view(customer)
        self.finish("customer.created", customer, payload.model_dump().keys())
        return result

    def update(self, customer_id: UUID, payload: CustomerWrite) -> CustomerView:
        self.begin("customers.update")
        customer = self.customer(customer_id)
        values = payload.model_dump()
        changed_fields = [
            field for field, value in values.items() if getattr(customer, field) != value
        ]
        for field, value in values.items():
            setattr(customer, field, value)
        self.db.flush()
        result = self.view(customer)
        self.finish("customer.updated", customer, changed_fields)
        return result

    def status(self, customer_id: UUID, active: bool, delete: bool = False) -> CustomerView:
        self.begin("customers.delete" if delete else "customers.deactivate")
        customer = self.customer(customer_id)
        customer.status = "active" if active else "inactive"
        if delete:
            customer.deleted_at = datetime.now(UTC)
        self.db.flush()
        result = self.view(customer)
        self.finish(
            "customer.deleted" if delete else ("customer.activated" if active else "customer.deactivated"),
            customer,
            ["status"],
        )
        return result
