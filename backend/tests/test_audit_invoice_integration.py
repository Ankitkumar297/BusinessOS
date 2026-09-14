"""Focused local tests for atomic Invoice audit integration."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import AuditLog, Invoice, InvoiceItem
from app.schemas.invoice import InvoiceWrite
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.invoice_service import InvoiceService
from tests.test_audit_customer_integration import context_for
from tests.test_customers import create as create_customer
from tests.test_invoices import confirmed, invoice
from tests.test_orders import create as create_order
from tests.test_products import create as create_product
from tests.test_team import owner, team_client


def invoice_audits(client, business_id: str, invoice_id: str | None = None) -> list[AuditLog]:
    with Session(client.test_engine) as session:
        statement = select(AuditLog).where(
            AuditLog.business_id == UUID(business_id),
            AuditLog.entity_type == "invoice",
        )
        if invoice_id is not None:
            statement = statement.where(AuditLog.entity_id == UUID(invoice_id))
        return list(session.scalars(statement.order_by(AuditLog.created_at, AuditLog.id)))


def test_invoice_issue_commits_exactly_one_safe_audit_with_unchanged_snapshot(team_client):
    headers, registration = owner(team_client)
    order, customer, _ = confirmed(team_client, headers, "SO-INVOICE-AUDIT")
    response = invoice(team_client, headers, order["id"])
    assert response.status_code == 201, response.text
    body = response.json()

    rows = invoice_audits(team_client, registration["business"]["id"], body["id"])
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "invoice.issued"
    assert row.entity_type == "invoice"
    assert row.entity_id == UUID(body["id"])
    assert row.entity_display == "INV-000001" == body["invoice_number"]
    assert row.business_id == UUID(registration["business"]["id"])
    assert row.actor_user_id == UUID(registration["user"]["id"])
    assert row.changed_fields == [
        "grand_total", "invoice_number", "issued_at", "items", "order_id",
        "status", "subtotal", "tax_total",
    ]
    assert all(value not in row.changed_fields for value in ("20.00", customer["display_name"]))
    assert body["grand_total"] == "20.00"
    assert body["customer_name"] == customer["display_name"]
    assert len(body["items"]) == 1
    with Session(team_client.test_engine) as session:
        assert session.scalar(select(func.count()).select_from(InvoiceItem).where(
            InvoiceItem.invoice_id == UUID(body["id"])
        )) == 1


def test_duplicate_unconfirmed_and_cross_tenant_attempts_create_no_invoice_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    confirmed_order, _, _ = confirmed(team_client, first_headers, "SO-INVOICE-FAILURES")
    made = invoice(team_client, first_headers, confirmed_order["id"])
    assert made.status_code == 201
    assert invoice(team_client, first_headers, confirmed_order["id"]).status_code == 409
    assert invoice(team_client, second_headers, confirmed_order["id"]).status_code == 404

    customer = create_customer(team_client, first_headers, "Draft Invoice Customer")
    product = create_product(
        team_client, first_headers, sku="DRAFT-INVOICE-AUDIT", barcode="DRAFT-INVOICE-AUDIT"
    )
    draft = create_order(
        team_client, first_headers, customer["id"], product["id"],
        order_number="SO-DRAFT-INVOICE-AUDIT",
    )
    assert invoice(team_client, first_headers, draft["id"]).status_code == 409
    rows = invoice_audits(team_client, first["business"]["id"])
    assert len(rows) == 1 and rows[0].entity_id == UUID(made.json()["id"])
    assert invoice_audits(team_client, second["business"]["id"]) == []


def test_forced_audit_failure_rolls_back_invoice_items_and_remains_distinct(team_client, monkeypatch):
    headers, registration = owner(team_client)
    order, _, _ = confirmed(team_client, headers, "SO-INVOICE-AUDIT-FAIL")
    context = context_for(team_client, registration["business"]["id"])

    def fail_record(self: AuditService, **_: object) -> AuditLog:
        raise AuditPersistenceError("forced invoice audit failure")

    monkeypatch.setattr(AuditService, "record", fail_record)
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError, match="forced invoice audit failure"):
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


def test_commit_failure_rolls_back_invoice_items_and_flushed_audit(team_client, monkeypatch):
    headers, registration = owner(team_client)
    order, _, _ = confirmed(team_client, headers, "SO-INVOICE-COMMIT-FAIL")
    context = context_for(team_client, registration["business"]["id"])
    session = Session(team_client.test_engine)
    monkeypatch.setattr(
        session, "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("forced invoice commit failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="forced invoice commit failure"):
            InvoiceService(session, context).create(InvoiceWrite(order_id=UUID(order["id"])))
        assert session.scalar(select(func.count()).select_from(Invoice).where(
            Invoice.order_id == UUID(order["id"])
        )) == 1
        assert session.scalar(select(func.count()).select_from(InvoiceItem)) == 1
        assert session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_type == "invoice"
        )) == 1
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


def test_genuine_domain_integrity_error_keeps_existing_conflict_mapping(team_client, monkeypatch):
    headers, registration = owner(team_client)
    order, _, _ = confirmed(team_client, headers, "SO-INVOICE-INTEGRITY")
    context = context_for(team_client, registration["business"]["id"])
    session = Session(team_client.test_engine)

    original_flush = session.flush

    def fail_domain_flush(*args: object, **kwargs: object) -> None:
        if any(isinstance(row, Invoice) for row in session.new):
            raise IntegrityError("forced invoice domain integrity error", {}, Exception("duplicate"))
        original_flush(*args, **kwargs)

    monkeypatch.setattr(session, "flush", fail_domain_flush)
    try:
        with pytest.raises(AppError) as caught:
            InvoiceService(session, context).create(InvoiceWrite(order_id=UUID(order["id"])))
        assert caught.value.status_code == 409
        assert caught.value.detail == "An invoice already exists for this order."
    finally:
        session.close()
