"""Real PostgreSQL verification for the tenant-scoped audit log read API."""
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.test_audit_logs_api import role_headers, seed_audit
from tests.test_customers import create as create_customer
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def test_postgres_tenant_filter_and_owner_admin_manager_employee_permissions(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    first_customer = create_customer(team_client, first_headers, "PG First Audit Customer")
    second_customer = create_customer(team_client, second_headers, "PG Second Audit Customer")

    for role_name in ("Admin", "Manager"):
        headers, _ = role_headers(team_client, first_headers, role_name)
        response = team_client.get(
            "/api/v1/audit-logs?entity_type=customer", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["entity_id"] == first_customer["id"]
        assert response.json()["items"][0]["business_id"] == first["business"]["id"]
        assert response.json()["items"][0]["entity_id"] != second_customer["id"]
        assert response.json()["items"][0]["business_id"] != second["business"]["id"]
    employee_headers, _ = role_headers(team_client, first_headers, "Employee")
    assert team_client.get("/api/v1/audit-logs", headers=employee_headers).status_code == 403
    assert team_client.get("/api/v1/audit-logs", headers=first_headers).status_code == 200


def test_postgres_deterministic_ordering_pagination_and_combined_filters(team_client):
    headers, registration = owner(team_client)
    _, second_actor = role_headers(team_client, headers, "Employee")
    entity_id = uuid4()
    timestamp = datetime(2026, 3, 4, 12, tzinfo=UTC)
    low_id, _ = seed_audit(
        team_client, registration, row_id=UUID(int=101), action="customer.updated",
        entity_type="customer", entity_id=entity_id, changed_fields=["email"],
        created_at=timestamp,
    )
    high_id, _ = seed_audit(
        team_client, registration, row_id=UUID(int=102), action="customer.updated",
        entity_type="customer", entity_id=entity_id, changed_fields=["phone"],
        created_at=timestamp,
    )
    seed_audit(
        team_client, registration, actor_id=UUID(second_actor["id"]),
        action="customer.updated", entity_type="customer", entity_id=entity_id,
        created_at=datetime(2026, 3, 5, 12, tzinfo=UTC),
    )

    base = (
        f"/api/v1/audit-logs?action=customer.updated&entity_type=customer"
        f"&entity_id={entity_id}&actor={registration['user']['id']}"
        "&start=2026-03-04&end=2026-03-04&page_size=1"
    )
    first = team_client.get(base + "&page=1", headers=headers).json()
    second = team_client.get(base + "&page=2", headers=headers).json()
    empty = team_client.get(base + "&page=3", headers=headers).json()
    assert first["total"] == second["total"] == empty["total"] == 2
    assert first["items"][0]["id"] == str(high_id)
    assert second["items"][0]["id"] == str(low_id)
    assert empty["items"] == []


def test_postgres_date_bounds_cross_tenant_and_append_only_contract(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    row_id, _ = seed_audit(
        team_client, first, action="role.deleted", entity_type="role",
        changed_fields=["is_active"], created_at=datetime(2026, 4, 2, 23, 59, tzinfo=UTC),
    )
    seed_audit(
        team_client, second, action="role.deleted", entity_type="role",
        changed_fields=["is_active"], created_at=datetime(2026, 4, 2, 12, tzinfo=UTC),
    )
    response = team_client.get(
        "/api/v1/audit-logs?action=role.deleted&start=2026-04-02&end=2026-04-02",
        headers=first_headers,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(row_id)
    assert response.json()["items"][0]["business_id"] == first["business"]["id"]
    assert team_client.get(
        "/api/v1/audit-logs?start=2026-04-03&end=2026-04-02", headers=first_headers
    ).status_code == 422
    assert team_client.post("/api/v1/audit-logs", headers=first_headers, json={}).status_code == 405
    with pytest.raises(IntegrityError, match="append-only"):
        with team_client.test_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM audit_logs WHERE id=:id"), {"id": row_id}
            )
