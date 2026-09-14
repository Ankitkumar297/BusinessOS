"""Focused local tests for the Customer audit pilot."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.models import AuditLog, Customer, User
from app.schemas.customer import CustomerWrite
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.customer_service import CustomerService
from tests.test_customers import create, payload
from tests.test_team import owner, team_client


def context_for(client, business_id: str) -> TenantContext:
    with Session(client.test_engine) as session:
        actor = session.scalar(select(User).where(User.business_id == UUID(business_id)))
        assert actor is not None
        return TenantContext(
            business_id=UUID(business_id),
            user_id=actor.id,
            permissions=frozenset(),
        )


def logs(client, business_id: str) -> list[AuditLog]:
    with Session(client.test_engine) as session:
        return list(
            session.scalars(
                select(AuditLog)
                .where(AuditLog.business_id == UUID(business_id))
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )


def test_customer_mutations_create_one_semantic_audit_each(team_client):
    headers, registration = owner(team_client)
    business_id = registration["business"]["id"]
    actor_id = registration["user"]["id"]
    customer = create(team_client, headers, "Audit Customer")

    created = logs(team_client, business_id)
    assert len(created) == 1
    assert created[0].action == "customer.created"
    assert created[0].entity_type == "customer"
    assert created[0].entity_id == UUID(customer["id"])
    assert created[0].business_id == UUID(business_id)
    assert created[0].actor_user_id == UUID(actor_id)
    assert created[0].actor_name_snapshot == registration["user"]["full_name"]
    assert created[0].actor_email_snapshot == registration["user"]["email"]
    assert created[0].entity_display == "Audit Customer"
    assert created[0].changed_fields == sorted(payload("Audit Customer").keys())

    update_payload = payload("Audit Customer Updated")
    response = team_client.patch(
        f"/api/v1/customers/{customer['id']}", headers=headers, json=update_payload
    )
    assert response.status_code == 200, response.text
    assert team_client.post(
        f"/api/v1/customers/{customer['id']}/deactivate", headers=headers
    ).status_code == 200
    assert team_client.post(
        f"/api/v1/customers/{customer['id']}/activate", headers=headers
    ).status_code == 200
    assert team_client.delete(
        f"/api/v1/customers/{customer['id']}", headers=headers
    ).status_code == 204

    rows = logs(team_client, business_id)
    by_action = {row.action: row for row in rows}
    assert len(rows) == len(by_action) == 5
    assert set(by_action) == {
        "customer.created", "customer.updated", "customer.deactivated",
        "customer.activated", "customer.deleted",
    }
    assert by_action["customer.updated"].entity_display == "Audit Customer Updated"
    assert by_action["customer.updated"].changed_fields == ["display_name", "email"]
    assert all(row.entity_id == UUID(customer["id"]) for row in rows)
    assert all(row.business_id == UUID(business_id) for row in rows)
    assert all(row.actor_user_id == UUID(actor_id) for row in rows)
    assert all(
        by_action[action].changed_fields == ["status"]
        for action in ("customer.deactivated", "customer.activated", "customer.deleted")
    )


def test_failed_cross_tenant_customer_mutation_creates_no_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    customer = create(team_client, first_headers, "Private Customer")
    before_first = len(logs(team_client, first["business"]["id"]))

    response = team_client.patch(
        f"/api/v1/customers/{customer['id']}",
        headers=second_headers,
        json=payload("Cross Tenant Update"),
    )
    assert response.status_code == 404
    assert len(logs(team_client, first["business"]["id"])) == before_first
    assert logs(team_client, second["business"]["id"]) == []


def test_forced_audit_failure_prevents_customer_commit(team_client, monkeypatch):
    _, registration = owner(team_client)
    context = context_for(team_client, registration["business"]["id"])
    customer_name = f"Audit failure {uuid4().hex}"

    def fail_record(self: AuditService, **_: object) -> AuditLog:
        raise AuditPersistenceError("forced audit failure")

    monkeypatch.setattr(AuditService, "record", fail_record)
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError, match="forced audit failure"):
            CustomerService(session, context).create(
                CustomerWrite.model_validate(payload(customer_name))
            )
        session.rollback()
    finally:
        session.close()

    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(
            select(func.count()).select_from(Customer).where(
                Customer.business_id == context.business_id,
                Customer.display_name == customer_name,
            )
        ) == 0
        assert fresh.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.business_id == context.business_id
            )
        ) == 0


def test_commit_failure_rolls_back_customer_and_flushed_audit(team_client, monkeypatch):
    _, registration = owner(team_client)
    context = context_for(team_client, registration["business"]["id"])
    customer_name = f"Commit failure {uuid4().hex}"
    session = Session(team_client.test_engine)
    monkeypatch.setattr(
        session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("forced commit failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="forced commit failure"):
            CustomerService(session, context).create(
                CustomerWrite.model_validate(payload(customer_name))
            )
        assert session.scalar(
            select(func.count()).select_from(Customer).where(
                Customer.display_name == customer_name
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.entity_display == customer_name
            )
        ) == 1
        session.rollback()
    finally:
        session.close()

    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(
            select(func.count()).select_from(Customer).where(
                Customer.display_name == customer_name
            )
        ) == 0
        assert fresh.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.entity_display == customer_name
            )
        ) == 0
