"""Focused local audit integration tests for Suppliers and Products."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Product, ProductSupplier, Supplier
from app.schemas.product import ProductWrite
from app.schemas.supplier import SupplierWrite
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.product_service import ProductService
from app.services.supplier_service import SupplierService
from tests.test_audit_customer_integration import context_for
from tests.test_products import create as create_product, payload as product_payload
from tests.test_suppliers import create as create_supplier, payload as supplier_payload
from tests.test_team import owner, team_client


def domain_logs(client, business_id: str, entity_type: str) -> list[AuditLog]:
    with Session(client.test_engine) as session:
        return list(session.scalars(select(AuditLog).where(
            AuditLog.business_id == UUID(business_id),
            AuditLog.entity_type == entity_type,
        )))


def test_supplier_lifecycle_is_audited_once_with_actual_changes(team_client):
    headers, registration = owner(team_client); business_id = registration["business"]["id"]
    supplier = create_supplier(team_client, headers, "Audit Supplier")
    update = supplier_payload("Audit Supplier Updated")
    assert team_client.patch(f"/api/v1/suppliers/{supplier['id']}", headers=headers, json=update).status_code == 200
    assert team_client.post(f"/api/v1/suppliers/{supplier['id']}/deactivate", headers=headers).status_code == 200
    assert team_client.post(f"/api/v1/suppliers/{supplier['id']}/activate", headers=headers).status_code == 200
    assert team_client.delete(f"/api/v1/suppliers/{supplier['id']}", headers=headers).status_code == 204
    rows = domain_logs(team_client, business_id, "supplier"); by_action = {row.action: row for row in rows}
    assert len(rows) == len(by_action) == 5
    assert set(by_action) == {"supplier.created", "supplier.updated", "supplier.deactivated", "supplier.activated", "supplier.deleted"}
    assert by_action["supplier.created"].entity_display == "Audit Supplier"
    assert by_action["supplier.updated"].entity_display == "Audit Supplier Updated"
    assert by_action["supplier.updated"].changed_fields == ["supplier_name"]
    assert all(by_action[action].changed_fields == ["status"] for action in ("supplier.deactivated", "supplier.activated", "supplier.deleted"))
    assert all(row.entity_id == UUID(supplier["id"]) for row in rows)
    assert all(row.actor_user_id == UUID(registration["user"]["id"]) for row in rows)


def test_product_lifecycle_and_supplier_links_have_distinct_events(team_client):
    headers, registration = owner(team_client); business_id = registration["business"]["id"]
    product = create_product(team_client, headers, "Audit Product")
    supplier = create_supplier(team_client, headers, "Linked Supplier")
    assert team_client.post(f"/api/v1/products/{product['id']}/suppliers", headers=headers, json={"supplier_id": supplier["id"], "purchase_cost": "8.00"}).status_code == 201
    assert team_client.delete(f"/api/v1/products/{product['id']}/suppliers/{supplier['id']}", headers=headers).status_code == 204
    assert team_client.patch(f"/api/v1/products/{product['id']}", headers=headers, json=product_payload("Audit Product Updated")).status_code == 200
    assert team_client.post(f"/api/v1/products/{product['id']}/deactivate", headers=headers).status_code == 200
    assert team_client.post(f"/api/v1/products/{product['id']}/activate", headers=headers).status_code == 200
    assert team_client.delete(f"/api/v1/products/{product['id']}", headers=headers).status_code == 204
    rows = domain_logs(team_client, business_id, "product"); by_action = {row.action: row for row in rows}
    assert len(rows) == len(by_action) == 7
    assert set(by_action) == {"product.created", "product.updated", "product.activated", "product.deactivated", "product.deleted", "product.supplier_added", "product.supplier_removed"}
    assert by_action["product.updated"].changed_fields == ["name"]
    assert by_action["product.supplier_added"].changed_fields == ["suppliers"]
    assert by_action["product.supplier_removed"].changed_fields == ["suppliers"]
    assert sum(row.action == "product.updated" for row in rows) == 1
    assert all(row.entity_id == UUID(product["id"]) for row in rows)


def test_cross_tenant_failures_create_no_supplier_or_product_audit(team_client):
    first_headers, first = owner(team_client); second_headers, second = owner(team_client, "Other")
    supplier = create_supplier(team_client, first_headers); product = create_product(team_client, first_headers)
    supplier_count = len(domain_logs(team_client, first["business"]["id"], "supplier"))
    product_count = len(domain_logs(team_client, first["business"]["id"], "product"))
    assert team_client.patch(f"/api/v1/suppliers/{supplier['id']}", headers=second_headers, json=supplier_payload()).status_code == 404
    assert team_client.patch(f"/api/v1/products/{product['id']}", headers=second_headers, json=product_payload()).status_code == 404
    assert len(domain_logs(team_client, first["business"]["id"], "supplier")) == supplier_count
    assert len(domain_logs(team_client, first["business"]["id"], "product")) == product_count
    assert domain_logs(team_client, second["business"]["id"], "supplier") == []
    assert domain_logs(team_client, second["business"]["id"], "product") == []


@pytest.mark.parametrize("domain", ["supplier", "product"])
def test_forced_audit_failure_rolls_back_domain_create(team_client, monkeypatch, domain: str):
    _, registration = owner(team_client); context = context_for(team_client, registration["business"]["id"]); marker = f"Failure {domain} {uuid4().hex}"
    monkeypatch.setattr(AuditService, "record", lambda self, **kwargs: (_ for _ in ()).throw(AuditPersistenceError("forced audit failure")))
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError):
            if domain == "supplier": SupplierService(session, context).create(SupplierWrite.model_validate(supplier_payload(marker, supplier_code=f"S-{uuid4().hex[:8]}")))
            else: ProductService(session, context).create(ProductWrite.model_validate(product_payload(marker, sku=f"P-{uuid4().hex[:8]}", barcode=None)))
        session.rollback()
    finally: session.close()
    with Session(team_client.test_engine) as fresh:
        model = Supplier if domain == "supplier" else Product; name_field = Supplier.supplier_name if domain == "supplier" else Product.name
        assert fresh.scalar(select(func.count()).select_from(model).where(name_field == marker)) == 0
        assert fresh.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_display == marker)) == 0


@pytest.mark.parametrize("domain", ["supplier", "product"])
def test_commit_failure_rolls_back_domain_and_audit(team_client, monkeypatch, domain: str):
    _, registration = owner(team_client); context = context_for(team_client, registration["business"]["id"]); marker = f"Commit {domain} {uuid4().hex}"
    session = Session(team_client.test_engine); monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("forced commit failure")))
    try:
        with pytest.raises(RuntimeError):
            if domain == "supplier": SupplierService(session, context).create(SupplierWrite.model_validate(supplier_payload(marker, supplier_code=f"S-{uuid4().hex[:8]}")))
            else: ProductService(session, context).create(ProductWrite.model_validate(product_payload(marker, sku=f"P-{uuid4().hex[:8]}", barcode=None)))
        model = Supplier if domain == "supplier" else Product
        name_field = Supplier.supplier_name if domain == "supplier" else Product.name
        assert session.scalar(select(func.count()).select_from(model).where(name_field == marker)) == 1
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_display == marker)) == 1
        session.rollback()
    finally: session.close()
    with Session(team_client.test_engine) as fresh:
        model = Supplier if domain == "supplier" else Product
        name_field = Supplier.supplier_name if domain == "supplier" else Product.name
        assert fresh.scalar(select(func.count()).select_from(model).where(name_field == marker)) == 0
        assert fresh.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_display == marker)) == 0


def test_noop_updates_preserve_success_with_empty_changed_fields(team_client):
    headers, registration = owner(team_client)
    supplier = create_supplier(team_client, headers); product = create_product(team_client, headers)
    assert team_client.patch(f"/api/v1/suppliers/{supplier['id']}", headers=headers, json=supplier_payload()).status_code == 200
    assert team_client.patch(f"/api/v1/products/{product['id']}", headers=headers, json=product_payload()).status_code == 200
    supplier_updates = [row for row in domain_logs(team_client, registration["business"]["id"], "supplier") if row.action == "supplier.updated"]
    product_updates = [row for row in domain_logs(team_client, registration["business"]["id"], "product") if row.action == "product.updated"]
    assert len(supplier_updates) == len(product_updates) == 1
    assert supplier_updates[0].changed_fields == []
    assert product_updates[0].changed_fields == []
