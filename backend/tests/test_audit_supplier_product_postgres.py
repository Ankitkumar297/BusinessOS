"""Real PostgreSQL checks for Supplier and Product audit integration."""
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
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

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only")


def test_postgres_supplier_product_and_links_commit_one_audit_each(team_client):
    headers, registration = owner(team_client); business_id = UUID(registration["business"]["id"])
    supplier = create_supplier(team_client, headers, "PG Supplier")
    product = create_product(team_client, headers, "PG Product")
    assert team_client.post(f"/api/v1/products/{product['id']}/suppliers", headers=headers, json={"supplier_id": supplier["id"]}).status_code == 201
    assert team_client.delete(f"/api/v1/products/{product['id']}/suppliers/{supplier['id']}", headers=headers).status_code == 204
    with Session(team_client.test_engine) as session:
        rows = list(session.scalars(select(AuditLog).where(AuditLog.business_id == business_id)))
        assert sum(row.action == "supplier.created" for row in rows) == 1
        assert sum(row.action == "product.created" for row in rows) == 1
        assert sum(row.action == "product.supplier_added" for row in rows) == 1
        assert sum(row.action == "product.supplier_removed" for row in rows) == 1
        assert sum(row.action == "product.updated" for row in rows) == 0
        assert session.scalar(select(func.count()).select_from(ProductSupplier).where(ProductSupplier.product_id == UUID(product["id"]))) == 1
        audit_id = next(row.id for row in rows if row.action == "product.supplier_added")
    with pytest.raises(IntegrityError, match="append-only"):
        with team_client.test_engine.begin() as connection:
            connection.execute(text("UPDATE audit_logs SET entity_display='changed' WHERE id=:id"), {"id": audit_id})


@pytest.mark.parametrize("domain", ["supplier", "product"])
def test_postgres_audit_failure_rolls_back_supplier_or_product(team_client, monkeypatch, domain: str):
    _, registration = owner(team_client); context = context_for(team_client, registration["business"]["id"]); marker = f"PG failure {domain} {uuid4().hex}"
    monkeypatch.setattr(AuditService, "record", lambda self, **kwargs: (_ for _ in ()).throw(AuditPersistenceError("forced audit failure")))
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError):
            if domain == "supplier": SupplierService(session, context).create(SupplierWrite.model_validate(supplier_payload(marker, supplier_code=f"S-{uuid4().hex[:8]}")))
            else: ProductService(session, context).create(ProductWrite.model_validate(product_payload(marker, sku=f"P-{uuid4().hex[:8]}", barcode=None)))
        session.rollback()
    finally: session.close()
    with Session(team_client.test_engine) as fresh:
        model = Supplier if domain == "supplier" else Product; field = Supplier.supplier_name if domain == "supplier" else Product.name
        assert fresh.scalar(select(func.count()).select_from(model).where(field == marker)) == 0
        assert fresh.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_display == marker)) == 0
