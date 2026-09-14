"""Focused local tests for atomic Team/User/Role audit integration."""
from collections import Counter
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Role, User
from app.schemas.team import RoleWrite, UserCreate
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.team_service import TeamService
import app.services.team_service as team_service_module
from tests.test_audit_customer_integration import context_for
from tests.test_team import member, owner, team_client


def team_audits(client, business_id: str, entity_type: str, entity_id: str | None = None) -> list[AuditLog]:
    with Session(client.test_engine) as session:
        statement = select(AuditLog).where(
            AuditLog.business_id == UUID(business_id), AuditLog.entity_type == entity_type,
        )
        if entity_id is not None:
            statement = statement.where(AuditLog.entity_id == UUID(entity_id))
        return list(session.scalars(statement.order_by(AuditLog.created_at, AuditLog.id)))


def create_role(client, headers, name: str = "Auditors", permissions: list[str] | None = None):
    response = client.post(
        "/api/v1/roles", headers=headers,
        json={"name": name, "description": "Audit role", "permission_codes": permissions or []},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_user_mutations_have_exact_semantic_audits_actor_target_and_post_commit_events(
    team_client, monkeypatch,
):
    headers, registration = owner(team_client)
    events = []
    monkeypatch.setattr(team_service_module, "publish_team_event", events.append)
    role = create_role(team_client, headers)
    target = member(team_client, headers)
    target_id = target["id"]
    changed = {"full_name": "Updated Team Member", "email": target["email"]}

    assert team_client.patch(f"/api/v1/users/{target_id}", headers=headers, json=changed).status_code == 200
    assert team_client.patch(f"/api/v1/users/{target_id}", headers=headers, json=changed).status_code == 200
    assert team_client.post(f"/api/v1/users/{target_id}/deactivate", headers=headers).status_code == 200
    assert team_client.post(f"/api/v1/users/{target_id}/activate", headers=headers).status_code == 200
    assert team_client.put(
        f"/api/v1/users/{target_id}/roles", headers=headers, json={"role_ids": [role["id"]]}
    ).status_code == 200
    assert team_client.put(
        f"/api/v1/users/{target_id}/roles", headers=headers, json={"role_ids": []}
    ).status_code == 200
    assert team_client.delete(f"/api/v1/users/{target_id}", headers=headers).status_code == 200

    rows = team_audits(team_client, registration["business"]["id"], "user", target_id)
    assert Counter(row.action for row in rows) == Counter({
        "user.created": 1, "user.updated": 2, "user.deactivated": 1,
        "user.activated": 1, "user.roles_changed": 2, "user.deleted": 1,
    })
    assert next(row for row in rows if row.action == "user.created").changed_fields == [
        "email", "full_name", "roles"
    ]
    updates = [row for row in rows if row.action == "user.updated"]
    assert sorted(tuple(row.changed_fields) for row in updates) == [(), ("full_name",)]
    assert all(
        row.changed_fields == ["is_active"] for row in rows
        if row.action in {"user.deactivated", "user.activated", "user.deleted"}
    )
    assert all(row.changed_fields == ["roles"] for row in rows if row.action == "user.roles_changed")
    assert all(row.actor_user_id == UUID(registration["user"]["id"]) for row in rows)
    assert all(row.entity_id == UUID(target_id) for row in rows)
    assert UUID(target_id) != UUID(registration["user"]["id"])
    assert next(row for row in rows if row.action == "user.deleted").entity_display == "Updated Team Member"
    created = next(row for row in rows if row.action == "user.created")
    assert "password" not in created.changed_fields and "password_hash" not in created.changed_fields
    target_events = [event for event in events if event.entity_id == UUID(target_id)]
    assert [event.name for event in target_events] == [
        "user.created", "user.updated", "user.updated", "user.deactivated",
        "user.activated", "user.roles_changed", "user.roles_changed", "user.deleted",
    ]


def test_role_mutations_have_exact_semantic_audits_and_noop_behavior(team_client):
    headers, registration = owner(team_client)
    role = create_role(team_client, headers, "Support Audit", ["users.view"])
    role_id = role["id"]
    update = {
        "name": "Customer Support Audit", "description": "Updated audit role",
        "permission_codes": ["roles.view"],
    }
    assert team_client.patch(f"/api/v1/roles/{role_id}", headers=headers, json=update).status_code == 200
    assert team_client.patch(f"/api/v1/roles/{role_id}", headers=headers, json=update).status_code == 200
    assert team_client.put(
        f"/api/v1/roles/{role_id}/permissions", headers=headers,
        json={"permission_codes": ["users.view"]},
    ).status_code == 200
    assert team_client.delete(f"/api/v1/roles/{role_id}", headers=headers).status_code == 204

    rows = team_audits(team_client, registration["business"]["id"], "role", role_id)
    assert Counter(row.action for row in rows) == Counter({
        "role.created": 1, "role.updated": 2,
        "role.permissions_changed": 1, "role.deleted": 1,
    })
    assert next(row for row in rows if row.action == "role.created").changed_fields == [
        "description", "name", "permissions"
    ]
    updates = [row for row in rows if row.action == "role.updated"]
    assert sorted(tuple(row.changed_fields) for row in updates) == [
        (), ("description", "name", "permissions")
    ]
    assert next(row for row in rows if row.action == "role.permissions_changed").changed_fields == ["permissions"]
    assert next(row for row in rows if row.action == "role.deleted").changed_fields == ["is_active"]
    assert all(row.entity_display in {"Support Audit", "Customer Support Audit"} for row in rows)
    assert all("users.view" not in row.changed_fields for row in rows)


def test_cross_tenant_and_protected_operations_create_no_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    target = member(team_client, first_headers)
    foreign_role = create_role(team_client, second_headers, "Foreign Audit Role")
    user_baseline = len(team_audits(team_client, first["business"]["id"], "user"))
    role_baseline = len(team_audits(team_client, first["business"]["id"], "role"))

    assert team_client.patch(
        f"/api/v1/users/{target['id']}", headers=second_headers,
        json={"full_name": "Cross Tenant", "email": target["email"]},
    ).status_code == 404
    assert team_client.put(
        f"/api/v1/users/{target['id']}/roles", headers=first_headers,
        json={"role_ids": [foreign_role["id"]]},
    ).status_code == 404
    system_owner = next(
        role for role in team_client.get("/api/v1/roles", headers=first_headers).json()
        if role["name"] == "Owner"
    )
    assert team_client.delete(f"/api/v1/roles/{system_owner['id']}", headers=first_headers).status_code == 409
    assert team_client.delete(
        f"/api/v1/users/{first['user']['id']}", headers=first_headers
    ).status_code == 409
    assert len(team_audits(team_client, first["business"]["id"], "user")) == user_baseline
    assert len(team_audits(team_client, first["business"]["id"], "role")) == role_baseline


@pytest.mark.parametrize("domain", ["user", "role"])
def test_forced_audit_failure_rolls_back_team_mutation_and_prevents_event(
    team_client, monkeypatch, domain: str,
):
    headers, registration = owner(team_client)
    context = context_for(team_client, registration["business"]["id"])
    events = []
    monkeypatch.setattr(team_service_module, "publish_team_event", events.append)

    def fail_record(self: AuditService, **_: object) -> AuditLog:
        raise AuditPersistenceError("forced team audit failure")

    monkeypatch.setattr(AuditService, "record", fail_record)
    marker = uuid4().hex
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError, match="forced team audit failure"):
            if domain == "user":
                TeamService(session, context).create_user(UserCreate(
                    full_name=f"Failed User {marker}", email=f"{marker}@example.com",
                    password="StrongPassword123!", role_ids=[],
                ))
            else:
                TeamService(session, context).write_role(RoleWrite(
                    name=f"Failed Role {marker}", description="rollback", permission_codes=[],
                ))
        session.rollback()
    finally:
        session.close()
    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(select(func.count()).select_from(User).where(User.email == f"{marker}@example.com")) == 0
        assert fresh.scalar(select(func.count()).select_from(Role).where(Role.name == f"Failed Role {marker}")) == 0
        assert fresh.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_display.in_([f"Failed User {marker}", f"Failed Role {marker}"])
        )) == 0
    assert events == []


def test_commit_failure_rolls_back_user_and_audit_and_prevents_event(team_client, monkeypatch):
    headers, registration = owner(team_client)
    context = context_for(team_client, registration["business"]["id"])
    marker = uuid4().hex
    display = f"Commit Failed User {marker}"
    email = f"commit-{marker}@example.com"
    events = []
    monkeypatch.setattr(team_service_module, "publish_team_event", events.append)
    session = Session(team_client.test_engine)
    monkeypatch.setattr(
        session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("forced team commit failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="forced team commit failure"):
            TeamService(session, context).create_user(UserCreate(
                full_name=display, email=email, password="StrongPassword123!", role_ids=[],
            ))
        assert session.scalar(select(func.count()).select_from(User).where(User.email == email)) == 1
        assert session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_display == display
        )) == 1
        session.rollback()
    finally:
        session.close()
    with Session(team_client.test_engine) as fresh:
        assert fresh.scalar(select(func.count()).select_from(User).where(User.email == email)) == 0
        assert fresh.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_display == display
        )) == 0
    assert events == []
