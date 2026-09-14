"""Real PostgreSQL verification for the audit schema and service contract."""
import os
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.models import AuditLog, Permission, Role, User
from app.services.audit_service import AuditService
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def audit_context(client, business_id: str) -> TenantContext:
    with Session(client.test_engine) as session:
        actor = session.scalar(
            select(User).where(User.business_id == UUID(business_id))
        )
        assert actor is not None
        return TenantContext(
            business_id=UUID(business_id),
            user_id=actor.id,
            permissions=frozenset({"audit.view"}),
        )


def test_postgres_audit_schema_constraints_indexes_and_permission_defaults(team_client):
    headers, registration = owner(team_client)
    del headers
    inspector = inspect(team_client.test_engine)
    columns = {column["name"] for column in inspector.get_columns("audit_logs")}
    foreign_keys = inspector.get_foreign_keys("audit_logs")
    indexes = {index["name"] for index in inspector.get_indexes("audit_logs")}
    user_indexes = {index["name"] for index in inspector.get_indexes("users")}
    with Session(team_client.test_engine) as session:
        permission = session.scalar(
            select(Permission).where(Permission.code == "audit.view")
        )
        assert permission is not None
        grants = {
            role.name: "audit.view" in {item.code for item in role.permissions}
            for role in session.scalars(
                select(Role).where(
                    Role.business_id == UUID(registration["business"]["id"]),
                    Role.is_system.is_(True),
                )
            )
        }

    assert {
        "id", "business_id", "actor_user_id", "actor_name_snapshot",
        "actor_email_snapshot", "action", "entity_type", "entity_id",
        "entity_display", "changed_fields", "created_at",
    } == columns
    assert any(
        foreign_key["constrained_columns"] == ["business_id", "actor_user_id"]
        and foreign_key["referred_table"] == "users"
        and foreign_key["referred_columns"] == ["business_id", "id"]
        for foreign_key in foreign_keys
    )
    assert any(
        foreign_key["constrained_columns"] == ["business_id"]
        and foreign_key["referred_table"] == "businesses"
        for foreign_key in foreign_keys
    )
    assert indexes == {
        "ix_audit_logs_business_created",
        "ix_audit_logs_business_action_created",
        "ix_audit_logs_business_entity",
        "ix_audit_logs_business_actor_created",
    }
    assert "uq_users_business_id" in user_indexes
    assert grants == {"Owner": True, "Admin": True, "Manager": True, "Employee": False}


def test_postgres_audit_actor_tenant_fk_and_append_only_trigger(team_client):
    _, first = owner(team_client)
    _, second = owner(team_client, "Other")
    context = audit_context(team_client, first["business"]["id"])
    with Session(team_client.test_engine) as session:
        record = AuditService(session, context).record(
            action="customer.created",
            entity_type="customer",
            entity_id=uuid4(),
            entity_display="Tenant customer",
        )
        record_id = record.id
        session.commit()

    with pytest.raises(IntegrityError, match="foreign key"):
        with team_client.test_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit_logs "
                    "(id,business_id,actor_user_id,actor_name_snapshot,"
                    "actor_email_snapshot,action,entity_type,entity_id,"
                    "changed_fields,created_at) VALUES "
                    "(:id,:business,:actor,'Actor','actor@example.com',"
                    "'customer.created','customer',:entity,'[]',now())"
                ),
                {
                    "id": uuid4(),
                    "business": UUID(second["business"]["id"]),
                    "actor": context.user_id,
                    "entity": uuid4(),
                },
            )

    for statement in (
        "UPDATE audit_logs SET entity_display='changed' WHERE id=:id",
        "UPDATE audit_logs SET business_id=:business WHERE id=:id",
        "DELETE FROM audit_logs WHERE id=:id",
    ):
        with pytest.raises(IntegrityError, match="append-only"):
            with team_client.test_engine.begin() as connection:
                connection.execute(
                    text(statement),
                    {
                        "id": record_id,
                        "business": UUID(second["business"]["id"]),
                    },
                )
    with Session(team_client.test_engine) as session:
        persisted = session.get(AuditLog, record_id)
        assert persisted is not None
        assert persisted.business_id == context.business_id
        persisted.entity_display = "ORM changed"
        with pytest.raises(IntegrityError, match="append-only"):
            session.flush()
        session.rollback()


def test_postgres_audit_service_uses_caller_commit_and_rollback(team_client):
    _, registration = owner(team_client)
    context = audit_context(team_client, registration["business"]["id"])
    rolled_back_id = committed_id = None
    with Session(team_client.test_engine) as session:
        rolled_back = AuditService(session, context).record(
            action="inventory.adjusted",
            entity_type="inventory",
            entity_id=uuid4(),
            changed_fields=["quantity_on_hand"],
        )
        rolled_back_id = rolled_back.id
        session.rollback()
    with Session(team_client.test_engine) as session:
        assert session.get(AuditLog, rolled_back_id) is None
        committed = AuditService(session, context).record(
            action="invoice.issued",
            entity_type="invoice",
            entity_id=uuid4(),
            changed_fields=["invoice_number"],
        )
        committed_id = committed.id
        session.commit()
    with Session(team_client.test_engine) as session:
        assert session.get(AuditLog, committed_id) is not None


def test_postgres_audit_migration_downgrade_reupgrade_and_permission_seed(team_client):
    _, registration = owner(team_client)
    config = Config("alembic.ini")
    with team_client.test_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0009_invoices")
        assert connection.scalar(text("SELECT to_regclass('audit_logs')")) is None
        assert connection.scalar(
            text("SELECT to_regprocedure('prevent_audit_log_mutation()')")
        ) is None
        permission_id = connection.scalar(
            text("SELECT id FROM permissions WHERE code='audit.view'")
        )
        assert permission_id is not None
        connection.execute(
            text("DELETE FROM role_permissions WHERE permission_id=:permission_id"),
            {"permission_id": permission_id},
        )
        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011_permission_backfill"
        assert connection.scalar(text("SELECT to_regclass('audit_logs')")) == "audit_logs"
        assert connection.scalar(
            text("SELECT to_regprocedure('prevent_audit_log_mutation()')")
        ) == "prevent_audit_log_mutation()"
    with Session(team_client.test_engine) as session:
        grants = {
            role.name: "audit.view" in {item.code for item in role.permissions}
            for role in session.scalars(
                select(Role).where(
                    Role.business_id == UUID(registration["business"]["id"]),
                    Role.is_system.is_(True),
                )
            )
        }
        assert grants == {"Owner": True, "Admin": True, "Manager": True, "Employee": False}
