from uuid import uuid4
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.models import Role, User
from app.services.auth_service import AuthService
from app.schemas.auth import RegistrationRequest


@pytest.fixture
def team_client():
    pg_url = os.environ.get("TEST_DATABASE_URL")
    admin_engine = None
    if pg_url:
        from alembic.config import Config
        from alembic import command
        schema = "test_" + uuid4().hex
        admin_engine = create_engine(pg_url)
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(pg_url, connect_args={"options": f"-csearch_path={schema}"})
        with engine.begin() as connection:
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
    else:
        engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
    def dependency():
        with Session(engine, expire_on_commit=False) as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    with TestClient(app) as client:
        client.test_engine = engine
        yield client
    app.dependency_overrides.clear()
    engine.dispose()
    if admin_engine:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def owner(client, name="Alpha"):
    response = client.post("/api/v1/auth/register", json={"business_name": name, "full_name": "Team Owner", "email": f"{uuid4().hex}@example.com", "password": "StrongPassword123!"})
    assert response.status_code == 201, response.text
    data = response.json()
    return {"Authorization": "Bearer " + data["access_token"]}, data


def member(client, headers, roles=()):
    response = client.post("/api/v1/users", headers=headers, json={"full_name": "Team Member", "email": f"{uuid4().hex}@example.com", "password": "StrongPassword123!", "role_ids": list(roles)})
    assert response.status_code == 201, response.text
    return response.json()


def test_authentication_permissions_and_crud(team_client):
    c = team_client
    assert c.get("/api/v1/users").status_code == 401
    h, data = owner(c)
    u = member(c, h)
    uid = u["id"]
    login = c.post("/api/v1/auth/login", json={"email": u["email"], "password": "StrongPassword123!"}).json()
    employee = {"Authorization": "Bearer " + login["access_token"]}
    assert c.get("/api/v1/users", headers=employee).status_code == 403
    assert c.get(f"/api/v1/users/{uid}", headers=h).status_code == 200
    assert c.patch(f"/api/v1/users/{uid}", headers=h, json={"full_name": "Updated Member", "email": u["email"]}).status_code == 200
    assert c.get("/api/v1/users?search=Updated&page_size=1", headers=h).json()["total"] == 1
    assert c.post(f"/api/v1/users/{uid}/deactivate", headers=h).status_code == 200
    assert c.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}).status_code == 401
    assert c.post(f"/api/v1/users/{uid}/activate", headers=h).status_code == 200
    assert c.get("/api/v1/auth/me", headers=employee).status_code == 401
    assert c.delete(f"/api/v1/users/{uid}", headers=h).status_code == 200
    assert c.get(f"/api/v1/users/{uid}", headers=h).status_code == 404


def test_role_crud_permissions_assignment_and_safe_delete(team_client):
    c = team_client; h, _ = owner(c)
    created = c.post("/api/v1/roles", headers=h, json={"name": "Support", "description": "Support team", "permission_codes": ["users.view"]})
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    assert c.put(f"/api/v1/roles/{rid}/permissions", headers=h, json={"permission_codes": ["users.view", "roles.view"]}).status_code == 200
    u = member(c, h, [rid])
    assert c.get(f"/api/v1/roles/{rid}", headers=h).json()["user_count"] == 1
    assert c.delete(f"/api/v1/roles/{rid}", headers=h).status_code == 409
    assert c.put(f"/api/v1/users/{u['id']}/roles", headers=h, json={"role_ids": []}).status_code == 200
    assert c.patch(f"/api/v1/roles/{rid}", headers=h, json={"name": "Customer Support", "permission_codes": []}).status_code == 200
    assert c.delete(f"/api/v1/roles/{rid}", headers=h).status_code == 204


def test_cross_tenant_and_privilege_escalation(team_client):
    c = team_client; h, data = owner(c); other_h, other = owner(c, "Beta")
    roles = c.get("/api/v1/roles", headers=h).json()
    admin_role = next(r for r in roles if r["name"] == "Admin")
    owner_role = next(r for r in roles if r["name"] == "Owner")
    foreign_role = c.get("/api/v1/roles", headers=other_h).json()[0]
    admin = member(c, h, [admin_role["id"]])
    employee = member(c, h)
    login = c.post("/api/v1/auth/login", json={"email": admin["email"], "password": "StrongPassword123!"}).json()
    ah = {"Authorization": "Bearer " + login["access_token"]}
    assert c.get(f"/api/v1/users/{other['user']['id']}", headers=h).status_code == 404
    assert c.put(f"/api/v1/users/{admin['id']}/roles", headers=h, json={"role_ids": [foreign_role["id"]]}).status_code == 404
    assert c.put(f"/api/v1/users/{admin['id']}/roles", headers=ah, json={"role_ids": [owner_role["id"]]}).status_code == 409
    assert c.put(f"/api/v1/users/{employee['id']}/roles", headers=ah, json={"role_ids": [owner_role["id"]]}).status_code == 403
    assert c.post("/api/v1/roles", headers=ah, json={"name": "Escalation", "permission_codes": ["settings.manage"]}).status_code == 403
    assert c.post(f"/api/v1/users/{data['user']['id']}/deactivate", headers=ah).status_code == 403
    assert c.delete(f"/api/v1/roles/{owner_role['id']}", headers=h).status_code == 409
    assert c.delete(f"/api/v1/users/{data['user']['id']}", headers=h).status_code == 409
    assert c.put(f"/api/v1/users/{data['user']['id']}/roles", headers=h, json={"role_ids": []}).status_code == 409


def test_tenant_payload_and_unknown_permissions_rejected(team_client):
    c = team_client; h, _ = owner(c)
    assert c.post("/api/v1/users", headers=h, json={"business_id": str(uuid4()), "full_name": "Other Member", "email": "member@example.com", "password": "StrongPassword123!", "role_ids": []}).status_code == 422
    assert c.post("/api/v1/roles", headers=h, json={"name": "Invalid Role", "permission_codes": ["unknown.admin"]}).status_code == 422
