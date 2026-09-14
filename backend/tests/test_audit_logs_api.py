"""Focused local tests for the read-only audit log API."""
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from tests.test_customers import create as create_customer
from tests.test_team import member, owner, team_client


def role_headers(client, owner_headers, role_name: str):
    role = next(row for row in client.get("/api/v1/roles", headers=owner_headers).json()
                if row["name"] == role_name)
    user = member(client, owner_headers, [role["id"]])
    login = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": "StrongPassword123!"},
    )
    assert login.status_code == 200
    return {"Authorization": "Bearer " + login.json()["access_token"]}, user


def seed_audit(
    client,
    registration,
    *,
    row_id: UUID | None = None,
    actor_id: UUID | None = None,
    action: str = "customer.updated",
    entity_type: str = "customer",
    entity_id: UUID | None = None,
    display: str = "Seeded entity",
    changed_fields: list[str] | None = None,
    created_at: datetime | None = None,
):
    actor_uuid = actor_id or UUID(registration["user"]["id"])
    with Session(client.test_engine) as session:
        actor = session.get(User, actor_uuid)
        assert actor is not None
        row = AuditLog(
            id=row_id or uuid4(),
            business_id=UUID(registration["business"]["id"]),
            actor_user_id=actor_uuid,
            actor_name_snapshot=actor.full_name,
            actor_email_snapshot=actor.email,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id or uuid4(),
            entity_display=display,
            changed_fields=changed_fields or [],
            created_at=created_at or datetime.now(UTC),
        )
        session.add(row)
        session.commit()
        return row.id, row.entity_id


@pytest.mark.parametrize("role_name", ["Owner", "Admin", "Manager"])
def test_owner_admin_and_manager_can_read_audit_logs(team_client, role_name):
    owner_headers, _ = owner(team_client)
    headers = owner_headers if role_name == "Owner" else role_headers(
        team_client, owner_headers, role_name
    )[0]
    response = team_client.get("/api/v1/audit-logs", headers=headers)
    assert response.status_code == 200
    assert response.json()["page"] == 1 and response.json()["page_size"] == 20


def test_employee_without_audit_view_is_denied(team_client):
    owner_headers, _ = owner(team_client)
    employee_headers, _ = role_headers(team_client, owner_headers, "Employee")
    assert team_client.get("/api/v1/audit-logs", headers=employee_headers).status_code == 403


def test_tenant_isolation_and_safe_response_fields(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    first_customer = create_customer(team_client, first_headers, "First Audit Customer")
    second_customer = create_customer(team_client, second_headers, "Second Audit Customer")

    response = team_client.get(
        "/api/v1/audit-logs?entity_type=customer", headers=first_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["business_id"] == first["business"]["id"]
    assert row["entity_id"] == first_customer["id"]
    assert row["entity_id"] != second_customer["id"]
    assert row["actor_user_id"] == first["user"]["id"]
    assert row["actor_name_snapshot"] == first["user"]["full_name"]
    assert row["actor_email_snapshot"] == first["user"]["email"]
    assert row["changed_fields"]
    assert all(item["business_id"] != second["business"]["id"] for item in body["items"])


def test_exact_and_combined_filters_with_inclusive_dates(team_client):
    headers, registration = owner(team_client)
    _, second_actor = role_headers(team_client, headers, "Employee")
    entity_id = uuid4()
    target_id, _ = seed_audit(
        team_client, registration,
        action="customer.updated", entity_type="customer", entity_id=entity_id,
        display="Filtered customer", changed_fields=["email"],
        created_at=datetime(2026, 1, 2, 12, tzinfo=UTC),
    )
    seed_audit(
        team_client, registration,
        actor_id=UUID(second_actor["id"]), action="customer.updated",
        entity_type="customer", entity_id=entity_id,
        created_at=datetime(2026, 1, 2, 13, tzinfo=UTC),
    )
    seed_audit(
        team_client, registration,
        action="customer.created", entity_type="customer",
        created_at=datetime(2026, 1, 3, 12, tzinfo=UTC),
    )

    owner_id = registration["user"]["id"]
    combined = team_client.get(
        f"/api/v1/audit-logs?action=customer.updated&entity_type=customer"
        f"&entity_id={entity_id}&actor={owner_id}&start=2026-01-02&end=2026-01-02",
        headers=headers,
    )
    assert combined.status_code == 200
    assert combined.json()["total"] == 1
    assert combined.json()["items"][0]["id"] == str(target_id)
    assert combined.json()["items"][0]["changed_fields"] == ["email"]
    assert team_client.get(
        "/api/v1/audit-logs?action=customer.created", headers=headers
    ).json()["total"] == 1
    assert team_client.get(
        f"/api/v1/audit-logs?entity_id={entity_id}", headers=headers
    ).json()["total"] == 2
    assert team_client.get(
        f"/api/v1/audit-logs?actor={second_actor['id']}&entity_type=customer",
        headers=headers,
    ).json()["total"] == 1
    assert team_client.get(
        "/api/v1/audit-logs?start=2026-01-03&entity_type=customer", headers=headers
    ).json()["total"] == 1
    assert team_client.get(
        "/api/v1/audit-logs?end=2026-01-02&entity_type=customer", headers=headers
    ).json()["total"] == 2


def test_deterministic_ordering_stable_pagination_and_empty_page(team_client):
    headers, registration = owner(team_client)
    timestamp = datetime(2026, 2, 1, 10, tzinfo=UTC)
    low_id, _ = seed_audit(
        team_client, registration, row_id=UUID(int=1), action="role.deleted",
        entity_type="role", changed_fields=["is_active"], created_at=timestamp,
    )
    high_id, _ = seed_audit(
        team_client, registration, row_id=UUID(int=2), action="role.deleted",
        entity_type="role", changed_fields=["is_active"], created_at=timestamp,
    )
    first = team_client.get(
        "/api/v1/audit-logs?action=role.deleted&page=1&page_size=1", headers=headers
    ).json()
    second = team_client.get(
        "/api/v1/audit-logs?action=role.deleted&page=2&page_size=1", headers=headers
    ).json()
    empty = team_client.get(
        "/api/v1/audit-logs?action=role.deleted&page=3&page_size=1", headers=headers
    ).json()
    assert first["total"] == second["total"] == empty["total"] == 2
    assert first["items"][0]["id"] == str(high_id)
    assert second["items"][0]["id"] == str(low_id)
    assert empty["items"] == [] and empty["page"] == 3 and empty["page_size"] == 1


def test_invalid_ranges_pagination_and_mutation_methods_are_rejected(team_client):
    headers, _ = owner(team_client)
    assert team_client.get(
        "/api/v1/audit-logs?start=2026-02-02&end=2026-02-01", headers=headers
    ).status_code == 422
    assert team_client.get("/api/v1/audit-logs?page=0", headers=headers).status_code == 422
    assert team_client.get("/api/v1/audit-logs?page_size=101", headers=headers).status_code == 422
    assert team_client.get(
        f"/api/v1/audit-logs?entity_id={uuid4()}", headers=headers
    ).json() == {"items": [], "total": 0, "page": 1, "page_size": 20}
    assert team_client.post("/api/v1/audit-logs", headers=headers, json={}).status_code == 405
    assert team_client.patch("/api/v1/audit-logs", headers=headers, json={}).status_code == 405
    assert team_client.delete("/api/v1/audit-logs", headers=headers).status_code == 405
