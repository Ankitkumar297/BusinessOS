"""Real PostgreSQL transaction proofs for Invoice audit integration."""
import os
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, Invoice, InvoiceItem
from app.schemas.invoice import InvoiceWrite
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.invoice_service import InvoiceService
from tests.test_audit_customer_integration import context_for
from tests.test_audit_invoice_integration import invoice_audits
from tests.test_customers import create as create_customer
from tests.test_invoices import confirmed, invoice
from tests.test_orders import create as create_order
from tests.test_products import create as create_product
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def test_postgres_invoice_and_items_commit_with_exactly_one_append_only_audit(team_client):
    headers, registration = owner(team_client)
    order, _, _ = confirmed(team_client, headers, "SO-PG-INVOICE-AUDIT")
    response = invoice(team_client, headers, order["id"])
    assert response.status_code == 201, response.text
    invoice_id = response.json()["id"]
    rows = invoice_audits(team_client, registration["business"]["id"], invoice_id)
    assert len(rows) == 1
    assert rows[0].action == "invoice.issued"
    assert rows[0].actor_user_id == UUID(registration["user"]["id"])
    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(select(func.count()).select_from(InvoiceItem).where(
            InvoiceItem.invoice_id == UUID(invoice_id)
        )) == 1
    with pytest.raises(IntegrityError, match="append-only"):
        with team_client.test_engine.begin() as connection:
            connection.execute(
                text("UPDATE audit_logs SET entity_display='changed' WHERE id=:id"),
                {"id": rows[0].id},
            )


@pytest.mark.parametrize("failure", ["audit", "commit"])
def test_postgres_failure_rolls_back_invoice_items_and_audit(team_client, monkeypatch, failure):
    headers, registration = owner(team_client)
    order, _, _ = confirmed(team_client, headers, f"SO-PG-INVOICE-{failure.upper()}")
    context = context_for(team_client, registration["business"]["id"])
    session = Session(team_client.test_engine)
    if failure == "audit":
        def fail_record(self: AuditService, **_: object) -> AuditLog:
            raise AuditPersistenceError("forced invoice audit failure")
        monkeypatch.setattr(AuditService, "record", fail_record)
        expected = AuditPersistenceError
    else:
        monkeypatch.setattr(
            session, "commit",
            lambda: (_ for _ in ()).throw(RuntimeError("forced invoice commit failure")),
        )
        expected = RuntimeError
    try:
        with pytest.raises(expected):
            InvoiceService(session, context).create(InvoiceWrite(order_id=UUID(order["id"])))
        session.rollback()
    finally:
        session.close()
    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(select(func.count()).select_from(Invoice).where(
            Invoice.order_id == UUID(order["id"])
        )) == 0
        assert fresh.scalar(select(func.count()).select_from(InvoiceItem)) == 0
        assert fresh.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_type == "invoice"
        )) == 0


def test_postgres_duplicate_cross_tenant_and_unconfirmed_attempts_create_no_new_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    confirmed_order, _, _ = confirmed(team_client, first_headers, "SO-PG-INVOICE-FAILURES")
    made = invoice(team_client, first_headers, confirmed_order["id"])
    assert made.status_code == 201
    assert invoice(team_client, first_headers, confirmed_order["id"]).status_code == 409
    assert invoice(team_client, second_headers, confirmed_order["id"]).status_code == 404

    customer = create_customer(team_client, first_headers, "PG Draft Invoice Customer")
    product = create_product(
        team_client, first_headers, sku="PG-DRAFT-INVOICE", barcode="PG-DRAFT-INVOICE"
    )
    draft = create_order(
        team_client, first_headers, customer["id"], product["id"],
        order_number="SO-PG-DRAFT-INVOICE",
    )
    assert invoice(team_client, first_headers, draft["id"]).status_code == 409
    assert len(invoice_audits(team_client, first["business"]["id"])) == 1
    assert invoice_audits(team_client, second["business"]["id"]) == []
