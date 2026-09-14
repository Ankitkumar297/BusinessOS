"""Real PostgreSQL transaction proofs for Team/User/Role audit integration."""
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, Role, User
from app.schemas.team import RoleWrite, UserCreate
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.team_service import TeamService
import app.services.team_service as team_service_module
from tests.test_audit_customer_integration import context_for
from tests.test_audit_team_integration import create_role, team_audits
from tests.test_team import member, owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def test_postgres_user_role_assignment_permission_and_soft_delete_audits_are_atomic(team_client):
    headers, registration = owner(team_client)
    role = create_role(team_client, headers, "PG Team Audit", ["users.view"])
    target = member(team_client, headers)
    assert team_client.put(
        f"/api/v1/users/{target['id']}/roles", headers=headers,
        json={"role_ids": [role["id"]]},
    ).status_code == 200
    assert team_client.put(
        f"/api/v1/roles/{role['id']}/permissions", headers=headers,
        json={"permission_codes": ["users.view", "roles.view"]},
    ).status_code == 200
    assert team_client.put(
        f"/api/v1/users/{target['id']}/roles", headers=headers, json={"role_ids": []}
    ).status_code == 200
    assert team_client.delete(f"/api/v1/users/{target['id']}", headers=headers).status_code == 200

    user_rows = team_audits(
        team_client, registration["business"]["id"], "user", target["id"]
    )
    role_rows = team_audits(
        team_client, registration["business"]["id"], "role", role["id"]
    )
    assert sum(row.action == "user.created" for row in user_rows) == 1
    assert sum(row.action == "user.roles_changed" for row in user_rows) == 2
    assert sum(row.action == "user.deleted" for row in user_rows) == 1
    assert sum(row.action == "role.created" for row in role_rows) == 1
    assert sum(row.action == "role.permissions_changed" for row in role_rows) == 1
    assert all(row.actor_user_id == UUID(registration["user"]["id"]) for row in user_rows + role_rows)
    assert all(row.business_id == UUID(registration["business"]["id"]) for row in user_rows + role_rows)
    assert all(row.entity_id == UUID(target["id"]) for row in user_rows)
    assert UUID(target["id"]) != UUID(registration["user"]["id"])
    with Session(team_client.test_engine) as fresh:
        persisted = fresh.get(User, UUID(target["id"]))
        assert persisted is not None and persisted.deleted_at is not None
    with pytest.raises(IntegrityError, match="append-only"):
        with team_client.test_engine.begin() as connection:
            connection.execute(
                text("UPDATE audit_logs SET entity_display='changed' WHERE id=:id"),
                {"id": user_rows[0].id},
            )


@pytest.mark.parametrize("domain", ["user", "role"])
def test_postgres_audit_failure_rolls_back_team_mutation_and_event(
    team_client, monkeypatch, domain: str,
):
    headers, registration = owner(team_client)
    context = context_for(team_client, registration["business"]["id"])
    marker = uuid4().hex
    events = []
    monkeypatch.setattr(team_service_module, "publish_team_event", events.append)

    def fail_record(self: AuditService, **_: object) -> AuditLog:
        raise AuditPersistenceError("forced postgres team audit failure")

    monkeypatch.setattr(AuditService, "record", fail_record)
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError, match="forced postgres team audit failure"):
            if domain == "user":
                TeamService(session, context).create_user(UserCreate(
                    full_name=f"PG Failed User {marker}", email=f"pg-{marker}@example.com",
                    password="StrongPassword123!", role_ids=[],
                ))
            else:
                TeamService(session, context).write_role(RoleWrite(
                    name=f"PG Failed Role {marker}", description="rollback", permission_codes=[],
                ))
        session.rollback()
    finally:
        session.close()
    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(select(func.count()).select_from(User).where(
            User.email == f"pg-{marker}@example.com"
        )) == 0
        assert fresh.scalar(select(func.count()).select_from(Role).where(
            Role.name == f"PG Failed Role {marker}"
        )) == 0
        assert fresh.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_display.in_([f"PG Failed User {marker}", f"PG Failed Role {marker}"])
        )) == 0
    assert events == []


@pytest.mark.parametrize("domain", ["user", "role"])
def test_postgres_commit_failure_rolls_back_team_domain_and_audit(
    team_client, monkeypatch, domain: str,
):
    headers, registration = owner(team_client)
    context = context_for(team_client, registration["business"]["id"])
    marker = uuid4().hex
    user_display = f"PG Commit User {marker}"
    role_display = f"PG Commit Role {marker}"
    events = []
    monkeypatch.setattr(team_service_module, "publish_team_event", events.append)
    session = Session(team_client.test_engine)
    monkeypatch.setattr(
        session, "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("forced postgres team commit failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="forced postgres team commit failure"):
            if domain == "user":
                TeamService(session, context).create_user(UserCreate(
                    full_name=user_display, email=f"commit-{marker}@example.com",
                    password="StrongPassword123!", role_ids=[],
                ))
            else:
                TeamService(session, context).write_role(RoleWrite(
                    name=role_display, description="rollback", permission_codes=[],
                ))
        session.rollback()
    finally:
        session.close()
    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(select(func.count()).select_from(User).where(
            User.email == f"commit-{marker}@example.com"
        )) == 0
        assert fresh.scalar(select(func.count()).select_from(Role).where(Role.name == role_display)) == 0
        assert fresh.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_display.in_([user_display, role_display])
        )) == 0
    assert events == []


def test_postgres_cross_tenant_and_protected_failures_create_no_team_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    target = member(team_client, first_headers)
    baseline = len(team_audits(team_client, first["business"]["id"], "user"))
    assert team_client.patch(
        f"/api/v1/users/{target['id']}", headers=second_headers,
        json={"full_name": "Cross Tenant", "email": target["email"]},
    ).status_code == 404
    owner_role = next(
        role for role in team_client.get("/api/v1/roles", headers=first_headers).json()
        if role["name"] == "Owner"
    )
    assert team_client.delete(f"/api/v1/roles/{owner_role['id']}", headers=first_headers).status_code == 409
    assert team_client.delete(
        f"/api/v1/users/{first['user']['id']}", headers=first_headers
    ).status_code == 409
    assert len(team_audits(team_client, first["business"]["id"], "user")) == baseline
    assert team_audits(team_client, second["business"]["id"], "user") == []
