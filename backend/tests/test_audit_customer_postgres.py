"""Real PostgreSQL atomicity checks for the Customer audit pilot."""
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, Customer
from app.schemas.customer import CustomerWrite
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.customer_service import CustomerService
from tests.test_audit_customer_integration import context_for
from tests.test_customers import payload
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def test_postgres_customer_and_audit_commit_once_and_remain_append_only(team_client):
    headers, registration = owner(team_client)
    response = team_client.post(
        "/api/v1/customers", headers=headers, json=payload("Postgres Audit Customer")
    )
    assert response.status_code == 201, response.text
    customer_id = UUID(response.json()["id"])
    business_id = UUID(registration["business"]["id"])
    with Session(team_client.test_engine) as session:
        rows = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.business_id == business_id,
                    AuditLog.entity_id == customer_id,
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].action == "customer.created"
        audit_id = rows[0].id
    with pytest.raises(IntegrityError, match="append-only"):
        with team_client.test_engine.begin() as connection:
            connection.execute(
                text("UPDATE audit_logs SET entity_display='changed' WHERE id=:id"),
                {"id": audit_id},
            )


def test_postgres_forced_audit_failure_rolls_back_customer(team_client, monkeypatch):
    _, registration = owner(team_client)
    context = context_for(team_client, registration["business"]["id"])
    customer_name = f"PG audit failure {uuid4().hex}"

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


def test_postgres_commit_failure_rolls_back_customer_and_audit(team_client, monkeypatch):
    _, registration = owner(team_client)
    context = context_for(team_client, registration["business"]["id"])
    customer_name = f"PG commit failure {uuid4().hex}"
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
