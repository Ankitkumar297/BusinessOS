"""Closed audit action registry and read representation."""
from datetime import datetime
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

AuditEntityType = Literal[
    "user", "role", "customer", "supplier", "product", "inventory",
    "order", "payment", "invoice",
]

AuditAction = Literal[
    "user.created", "user.updated", "user.activated", "user.deactivated",
    "user.deleted", "user.roles_changed", "role.created", "role.updated",
    "role.permissions_changed", "role.deleted", "customer.created",
    "customer.updated", "customer.activated", "customer.deactivated",
    "customer.deleted", "supplier.created", "supplier.updated",
    "supplier.activated", "supplier.deactivated", "supplier.deleted",
    "product.created", "product.updated", "product.activated",
    "product.deactivated", "product.deleted", "product.supplier_added",
    "product.supplier_removed", "inventory.adjusted", "order.created",
    "order.updated", "order.confirmed", "order.cancelled", "payment.created",
    "payment.updated", "invoice.issued",
]

_ACTION_ENTITIES = {
    "user.created": "user", "user.updated": "user",
    "user.activated": "user", "user.deactivated": "user",
    "user.deleted": "user", "user.roles_changed": "user",
    "role.created": "role", "role.updated": "role",
    "role.permissions_changed": "role", "role.deleted": "role",
    "customer.created": "customer", "customer.updated": "customer",
    "customer.activated": "customer", "customer.deactivated": "customer",
    "customer.deleted": "customer",
    "supplier.created": "supplier", "supplier.updated": "supplier",
    "supplier.activated": "supplier", "supplier.deactivated": "supplier",
    "supplier.deleted": "supplier",
    "product.created": "product", "product.updated": "product",
    "product.activated": "product", "product.deactivated": "product",
    "product.deleted": "product", "product.supplier_added": "product",
    "product.supplier_removed": "product",
    "inventory.adjusted": "inventory",
    "order.created": "order", "order.updated": "order",
    "order.confirmed": "order", "order.cancelled": "order",
    "payment.created": "payment", "payment.updated": "payment",
    "invoice.issued": "invoice",
}
AUDIT_ACTION_ENTITIES = MappingProxyType(_ACTION_ENTITIES)

_USER_WRITE = frozenset({"full_name", "email", "roles"})
_ROLE_WRITE = frozenset({"name", "description", "permissions"})
_CUSTOMER_WRITE = frozenset({
    "customer_type", "display_name", "company_name", "email", "phone",
    "alternate_phone", "address_line_1", "address_line_2", "city", "state",
    "postal_code", "country", "tax_id", "notes",
})
_SUPPLIER_WRITE = frozenset({
    "supplier_name", "company_name", "supplier_code", "tax_id",
    "registration_number", "contact_person_name", "email", "phone",
    "alternate_phone", "address_line_1", "address_line_2", "city", "state",
    "postal_code", "country", "payment_terms", "lead_time_days",
    "minimum_order_value", "currency", "notes",
})
_PRODUCT_WRITE = frozenset({
    "name", "sku", "barcode", "description", "category", "brand",
    "unit_of_measure", "selling_price", "cost_price", "tax_rate",
    "track_inventory", "reorder_level", "notes",
})
_ORDER_WRITE = frozenset({
    "customer_id", "order_number", "order_date", "notes", "items",
})
_PAYMENT_WRITE = frozenset({
    "order_id", "payment_number", "amount", "payment_method", "status",
    "paid_at", "external_reference", "notes",
})

_ACTION_CHANGED_FIELDS = {
    "user.created": _USER_WRITE, "user.updated": frozenset({"full_name", "email"}),
    "user.activated": frozenset({"is_active"}),
    "user.deactivated": frozenset({"is_active"}),
    "user.deleted": frozenset({"is_active"}),
    "user.roles_changed": frozenset({"roles"}),
    "role.created": _ROLE_WRITE, "role.updated": _ROLE_WRITE,
    "role.permissions_changed": frozenset({"permissions"}),
    "role.deleted": frozenset({"is_active"}),
    "customer.created": _CUSTOMER_WRITE, "customer.updated": _CUSTOMER_WRITE,
    "customer.activated": frozenset({"status"}),
    "customer.deactivated": frozenset({"status"}),
    "customer.deleted": frozenset({"status"}),
    "supplier.created": _SUPPLIER_WRITE, "supplier.updated": _SUPPLIER_WRITE,
    "supplier.activated": frozenset({"status"}),
    "supplier.deactivated": frozenset({"status"}),
    "supplier.deleted": frozenset({"status"}),
    "product.created": _PRODUCT_WRITE, "product.updated": _PRODUCT_WRITE,
    "product.activated": frozenset({"status"}),
    "product.deactivated": frozenset({"status"}),
    "product.deleted": frozenset({"status"}),
    "product.supplier_added": frozenset({"suppliers"}),
    "product.supplier_removed": frozenset({"suppliers"}),
    "inventory.adjusted": frozenset({"quantity_on_hand"}),
    "order.created": _ORDER_WRITE, "order.updated": _ORDER_WRITE,
    "order.confirmed": frozenset({"status"}),
    "order.cancelled": frozenset({"status"}),
    "payment.created": _PAYMENT_WRITE, "payment.updated": _PAYMENT_WRITE,
    "invoice.issued": frozenset({
        "order_id", "invoice_number", "status", "issued_at", "items",
        "subtotal", "tax_total", "grand_total",
    }),
}
AUDIT_ACTION_CHANGED_FIELDS = MappingProxyType(_ACTION_CHANGED_FIELDS)


class AuditLogView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    business_id: UUID
    actor_user_id: UUID
    actor_name_snapshot: str
    actor_email_snapshot: str
    action: AuditAction
    entity_type: AuditEntityType
    entity_id: UUID
    entity_display: str | None
    changed_fields: list[str]
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogView]
    total: int
    page: int
    page_size: int
