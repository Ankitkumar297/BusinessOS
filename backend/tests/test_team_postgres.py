"""Concurrency and database invariants require the isolated PostgreSQL test stack."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.test_team import team_client, owner, member

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="Run docker/compose.test.yml for PostgreSQL coverage")


def test_database_rejects_cross_tenant_assignment(team_client):
    c = team_client; first, a = owner(c); second, b = owner(c, "Beta")
    role = c.get("/api/v1/roles", headers=second).json()[0]
    with pytest.raises(IntegrityError):
        with c.test_engine.begin() as connection:
            connection.execute(text("INSERT INTO user_roles(user_id,role_id) VALUES (:u,:r)"), {"u": UUID(a["user"]["id"]), "r": UUID(role["id"])})
    with pytest.raises(IntegrityError):
        with c.test_engine.begin() as connection:
            connection.execute(text("UPDATE users SET business_id=:b WHERE id=:u"), {"b": UUID(b["business"]["id"]), "u": UUID(a["user"]["id"])})


def test_refresh_race_rotates_once(team_client):
    c = team_client; _, a = owner(c)
    def refresh():
        return c.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]})
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: refresh(), range(2)))
    assert sorted(r.status_code for r in results) == [200, 401]


def test_concurrent_owner_deactivation_keeps_one_owner(team_client):
    c = team_client; first, a = owner(c)
    owner_role = next(r for r in c.get("/api/v1/roles", headers=first).json() if r["name"] == "Owner")
    b = member(c, first, [owner_role["id"]])
    session = c.post("/api/v1/auth/login", json={"email": b["email"], "password": "StrongPassword123!"}).json()
    second = {"Authorization": "Bearer " + session["access_token"]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        calls = [executor.submit(c.post, f"/api/v1/users/{b['id']}/deactivate", headers=first),
                 executor.submit(c.post, f"/api/v1/users/{a['user']['id']}/deactivate", headers=second)]
        statuses = sorted(call.result().status_code for call in calls)
    assert statuses[0] == 200 and statuses[1] in (401, 403)
    with c.test_engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.name='Owner' AND u.is_active AND u.deleted_at IS NULL")).scalar()
    assert count == 1
