"""Real PostgreSQL transaction proofs for Payment audit integration."""
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, Payment
from app.schemas.payment import PaymentUpdate
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.payment_service import PaymentService
from tests.test_audit_customer_integration import context_for
from tests.test_audit_payment_integration import payment_audits, write
from tests.test_customers import create as create_customer
from tests.test_orders import create as create_order
from tests.test_payments import confirmed, payment
from tests.test_products import create as create_product
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def test_postgres_payment_create_update_commit_with_tenant_actor_and_append_only_audit(team_client):
    headers, registration = owner(team_client)
    order = confirmed(team_client, headers)
    created = payment(team_client, headers, order["id"], "PAY-PG-AUDIT", "5.00", "pending")
    assert created.status_code == 201
    payment_id = created.json()["id"]
    assert team_client.patch(
        f"/api/v1/payments/{payment_id}", headers=headers, json={"notes": "received"}
    ).status_code == 200

    rows = payment_audits(team_client, registration["business"]["id"], payment_id)
    assert len(rows) == 2
    assert {row.action for row in rows} == {"payment.created", "payment.updated"}
    assert all(row.business_id == UUID(registration["business"]["id"]) for row in rows)
    assert all(row.actor_user_id == UUID(registration["user"]["id"]) for row in rows)
    updated = next(row for row in rows if row.action == "payment.updated")
    assert updated.changed_fields == ["notes"]
    with pytest.raises(IntegrityError, match="append-only"):
        with team_client.test_engine.begin() as connection:
            connection.execute(
                text("UPDATE audit_logs SET entity_display='changed' WHERE id=:id"),
                {"id": rows[0].id},
            )


@pytest.mark.parametrize("operation", ["create", "update"])
def test_postgres_audit_failure_rolls_back_payment_create_or_update(
    team_client, monkeypatch, operation: str
):
    headers, registration = owner(team_client)
    order = confirmed(team_client, headers)
    context = context_for(team_client, registration["business"]["id"])
    number = f"PAY-PG-{operation.upper()}-{uuid4().hex[:8]}"
    payment_id = None
    if operation == "update":
        created = payment(team_client, headers, order["id"], number, "5.00", "pending")
        assert created.status_code == 201
        payment_id = created.json()["id"]

    def fail_record(self: AuditService, **_: object) -> AuditLog:
        raise AuditPersistenceError("forced payment audit failure")

    monkeypatch.setattr(AuditService, "record", fail_record)
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError, match="forced payment audit failure"):
            if operation == "create":
                PaymentService(session, context).create(write(order["id"], number))
            else:
                PaymentService(session, context).update(
                    UUID(payment_id), PaymentUpdate(notes="must rollback")
                )
        session.rollback()
    finally:
        session.close()

    with Session(team_client.test_engine) as fresh:
        rows = list(fresh.scalars(select(Payment).where(Payment.payment_number == number)))
        if operation == "create":
            assert rows == []
            expected_audits = 0
        else:
            assert len(rows) == 1 and rows[0].notes is None
            expected_audits = 1
        assert fresh.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.entity_display == number)
        ) == expected_audits


def test_postgres_commit_failure_rolls_back_payment_and_audit(team_client, monkeypatch):
    headers, registration = owner(team_client)
    order = confirmed(team_client, headers)
    context = context_for(team_client, registration["business"]["id"])
    number = f"PAY-PG-COMMIT-{uuid4().hex[:8]}"
    session = Session(team_client.test_engine)
    monkeypatch.setattr(
        session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("forced payment commit failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="forced payment commit failure"):
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


def test_postgres_cross_tenant_and_unconfirmed_order_rejections_create_no_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    confirmed_order = confirmed(team_client, first_headers)
    assert payment(
        team_client, second_headers, confirmed_order["id"], "PAY-PG-CROSS", "1.00"
    ).status_code == 404

    customer = create_customer(team_client, first_headers, "PG Draft Payment Customer")
    product = create_product(team_client, first_headers, sku="PG-DRAFT-PAY", barcode="PG-DRAFT-PAY")
    draft = create_order(
        team_client, first_headers, customer["id"], product["id"],
        order_number="SO-PG-DRAFT-PAY",
    )
    assert payment(
        team_client, first_headers, draft["id"], "PAY-PG-DRAFT", "1.00"
    ).status_code == 409
    assert payment_audits(team_client, first["business"]["id"]) == []
    assert payment_audits(team_client, second["business"]["id"]) == []

