"""Focused local tests for atomic Payment audit integration."""
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Payment
from app.schemas.payment import PaymentUpdate, PaymentWrite
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.payment_service import PaymentService
from tests.test_audit_customer_integration import context_for
from tests.test_customers import create as create_customer
from tests.test_orders import create as create_order
from tests.test_payments import confirmed, payment
from tests.test_products import create as create_product
from tests.test_team import owner, team_client


def payment_audits(client, business_id: str, payment_id: str | None = None) -> list[AuditLog]:
    with Session(client.test_engine) as session:
        statement = select(AuditLog).where(
            AuditLog.business_id == UUID(business_id),
            AuditLog.entity_type == "payment",
        )
        if payment_id is not None:
            statement = statement.where(AuditLog.entity_id == UUID(payment_id))
        return list(session.scalars(statement.order_by(AuditLog.created_at, AuditLog.id)))


def write(order_id: str, number: str, *, status: str = "pending", amount: str = "5.00") -> PaymentWrite:
    return PaymentWrite(
        order_id=UUID(order_id),
        payment_number=number,
        amount=Decimal(amount),
        payment_method="cash",
        status=status,
    )


def test_payment_create_update_and_noop_are_audited_once_with_safe_metadata(team_client):
    headers, registration = owner(team_client)
    order = confirmed(team_client, headers)
    created = payment(team_client, headers, order["id"], "PAY-AUDIT", "5.00", "pending")
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]

    rows = payment_audits(team_client, registration["business"]["id"], payment_id)
    assert len(rows) == 1
    assert rows[0].action == "payment.created"
    assert rows[0].entity_type == "payment"
    assert rows[0].entity_id == UUID(payment_id)
    assert rows[0].entity_display == "PAY-AUDIT"
    assert rows[0].business_id == UUID(registration["business"]["id"])
    assert rows[0].actor_user_id == UUID(registration["user"]["id"])
    assert rows[0].changed_fields == [
        "amount", "external_reference", "notes", "order_id", "paid_at",
        "payment_method", "payment_number", "status",
    ]
    assert not hasattr(rows[0], "amount")
    assert not hasattr(rows[0], "payment_method")

    assert team_client.patch(
        f"/api/v1/payments/{payment_id}", headers=headers, json={"notes": "received"}
    ).status_code == 200
    assert team_client.patch(
        f"/api/v1/payments/{payment_id}", headers=headers, json={"notes": "received"}
    ).status_code == 200
    rows = payment_audits(team_client, registration["business"]["id"], payment_id)
    assert len(rows) == 3
    assert sum(row.action == "payment.created" for row in rows) == 1
    updates = [row for row in rows if row.action == "payment.updated"]
    assert len(updates) == 2
    assert sorted(tuple(row.changed_fields) for row in updates) == [(), ("notes",)]


def test_cross_tenant_unconfirmed_order_and_invalid_lifecycle_create_no_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    confirmed_order = confirmed(team_client, first_headers)
    completed = payment(
        team_client, first_headers, confirmed_order["id"], "PAY-COMPLETE", "5.00", "completed"
    )
    assert completed.status_code == 201
    first_baseline = len(payment_audits(team_client, first["business"]["id"]))

    assert team_client.patch(
        f"/api/v1/payments/{completed.json()['id']}",
        headers=second_headers,
        json={"notes": "cross tenant"},
    ).status_code == 404
    assert team_client.patch(
        f"/api/v1/payments/{completed.json()['id']}",
        headers=first_headers,
        json={"amount": "3.00"},
    ).status_code == 409
    assert payment(
        team_client, second_headers, confirmed_order["id"], "PAY-CROSS", "1.00"
    ).status_code == 404

    draft_customer = create_customer(team_client, first_headers, "Draft Payment Customer")
    draft_product = create_product(
        team_client, first_headers, sku="DRAFT-PAY", barcode="DRAFT-PAY"
    )
    draft = create_order(
        team_client, first_headers, draft_customer["id"], draft_product["id"],
        order_number="SO-DRAFT-PAY",
    )
    assert payment(team_client, first_headers, draft["id"], "PAY-DRAFT", "1.00").status_code == 409
    assert len(payment_audits(team_client, first["business"]["id"])) == first_baseline
    assert payment_audits(team_client, second["business"]["id"]) == []


def test_forced_audit_failure_rolls_back_payment_create(team_client, monkeypatch):
    headers, registration = owner(team_client)
    order = confirmed(team_client, headers)
    context = context_for(team_client, registration["business"]["id"])
    number = f"PAY-CREATE-FAIL-{uuid4().hex[:8]}"

    def fail_record(self: AuditService, **_: object) -> AuditLog:
        raise AuditPersistenceError("forced payment audit failure")

    monkeypatch.setattr(AuditService, "record", fail_record)
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError, match="forced payment audit failure"):
            PaymentService(session, context).create(write(order["id"], number))
        session.rollback()
    finally:
        session.close()

    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(
            select(func.count()).select_from(Payment).where(Payment.payment_number == number)
        ) == 0
        assert fresh.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.entity_display == number)
        ) == 0


def test_forced_audit_failure_rolls_back_payment_update(team_client, monkeypatch):
    headers, registration = owner(team_client)
    order = confirmed(team_client, headers)
    created = payment(team_client, headers, order["id"], "PAY-UPDATE-FAIL", "5.00", "pending")
    assert created.status_code == 201
    payment_id = created.json()["id"]
    context = context_for(team_client, registration["business"]["id"])

    def fail_record(self: AuditService, **_: object) -> AuditLog:
        raise AuditPersistenceError("forced payment audit failure")

    monkeypatch.setattr(AuditService, "record", fail_record)
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError, match="forced payment audit failure"):
            PaymentService(session, context).update(
                UUID(payment_id), PaymentUpdate(notes="must rollback")
            )
        session.rollback()
    finally:
        session.close()

    with Session(team_client.test_engine) as fresh:
        persisted = fresh.get(Payment, UUID(payment_id))
        assert persisted is not None and persisted.notes is None
    rows = payment_audits(team_client, registration["business"]["id"], payment_id)
    assert len(rows) == 1 and rows[0].action == "payment.created"


def test_commit_failure_rolls_back_payment_and_flushed_audit(team_client, monkeypatch):
    headers, registration = owner(team_client)
    order = confirmed(team_client, headers)
    context = context_for(team_client, registration["business"]["id"])
    number = f"PAY-COMMIT-FAIL-{uuid4().hex[:8]}"
    session = Session(team_client.test_engine)
    monkeypatch.setattr(
        session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("forced payment commit failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="forced payment commit failure"):
            PaymentService(session, context).create(write(order["id"], number))
        assert session.scalar(
            select(func.count()).select_from(Payment).where(Payment.payment_number == number)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.entity_display == number)
        ) == 1
        session.rollback()
    finally:
        session.close()

    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(
            select(func.count()).select_from(Payment).where(Payment.payment_number == number)
        ) == 0
        assert fresh.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.entity_display == number)
        ) == 0

