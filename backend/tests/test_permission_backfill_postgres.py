"""Real PostgreSQL verification for the existing-business permission backfill."""
import os
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)

TARGETS = {
    "inventory.adjust": "Adjust inventory",
    "payments.create": "Create payments",
    "payments.update": "Update payments",
}


def test_postgres_fresh_head_has_permission_definitions_and_defaults(team_client):
    _, registration = owner(team_client)
    business_id = UUID(registration["business"]["id"])
    with team_client.test_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011_permission_backfill"
        definitions = dict(
            connection.execute(
                text(
                    "SELECT code,description FROM permissions WHERE code IN "
                    "('inventory.adjust','payments.create','payments.update')"
                )
            ).all()
        )
        grants = connection.execute(
            text(
                "SELECT r.name,p.code FROM roles r "
                "LEFT JOIN role_permissions rp ON rp.role_id=r.id "
                "LEFT JOIN permissions p ON p.id=rp.permission_id AND p.code IN "
                "('inventory.adjust','payments.create','payments.update') "
                "WHERE r.business_id=:business_id AND r.is_system IS TRUE"
            ),
            {"business_id": business_id},
        ).all()
    by_role = {name: set() for name in ("Owner", "Admin", "Manager", "Employee")}
    for role_name, code in grants:
        if code:
            by_role[role_name].add(code)
    assert definitions == TARGETS
    assert by_role == {
        "Owner": set(TARGETS),
        "Admin": set(TARGETS),
        "Manager": set(),
        "Employee": set(),
    }


def test_postgres_backfills_existing_system_roles_idempotently(team_client):
    _, first = owner(team_client)
    _, second = owner(team_client, "Second")
    business_ids = [UUID(first["business"]["id"]), UUID(second["business"]["id"])]
    existing_permission_id = uuid4()
    custom_role_id = uuid4()
    config = Config("alembic.ini")

    with team_client.test_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0010_audit_logs")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010_audit_logs"

        unrelated_permission_count = connection.scalar(
            text(
                "SELECT count(*) FROM permissions WHERE code NOT IN "
                "('inventory.adjust','payments.create','payments.update')"
            )
        )
        unrelated_link_count = connection.scalar(
            text(
                "SELECT count(*) FROM role_permissions rp JOIN permissions p "
                "ON p.id=rp.permission_id WHERE p.code NOT IN "
                "('inventory.adjust','payments.create','payments.update')"
            )
        )

        first_owner_id = connection.scalar(
            text(
                "SELECT id FROM roles WHERE business_id=:business_id "
                "AND name='Owner' AND is_system IS TRUE"
            ),
            {"business_id": business_ids[0]},
        )
        connection.execute(
            text(
                "INSERT INTO roles "
                "(id,business_id,name,description,is_system,is_active) "
                "VALUES (:id,:business_id,'Backfill custom','Unchanged custom role',false,true)"
            ),
            {"id": custom_role_id, "business_id": business_ids[0]},
        )
        connection.execute(
            text(
                "DELETE FROM permissions WHERE code IN "
                "('inventory.adjust','payments.create','payments.update')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO permissions (id,code,description) "
                "VALUES (:id,'inventory.adjust','Existing description')"
            ),
            {"id": existing_permission_id},
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions (role_id,permission_id) VALUES "
                "(:owner_id,:permission_id),(:custom_id,:permission_id)"
            ),
            {
                "owner_id": first_owner_id,
                "custom_id": custom_role_id,
                "permission_id": existing_permission_id,
            },
        )

        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011_permission_backfill"

        permission_rows = connection.execute(
            text(
                "SELECT id,code,description FROM permissions WHERE code IN "
                "('inventory.adjust','payments.create','payments.update') ORDER BY code"
            )
        ).all()
        assert len(permission_rows) == 3
        permission_map = {row.code: row for row in permission_rows}
        assert permission_map["inventory.adjust"].id == existing_permission_id
        assert permission_map["inventory.adjust"].description == "Existing description"
        assert permission_map["payments.create"].description == TARGETS["payments.create"]
        assert permission_map["payments.update"].description == TARGETS["payments.update"]

        grants = connection.execute(
            text(
                "SELECT r.business_id,r.name,r.is_system,p.code FROM roles r "
                "LEFT JOIN role_permissions rp ON rp.role_id=r.id "
                "LEFT JOIN permissions p ON p.id=rp.permission_id AND p.code IN "
                "('inventory.adjust','payments.create','payments.update') "
                "WHERE r.business_id IN (:first,:second) "
                "ORDER BY r.business_id,r.name,p.code"
            ),
            {"first": business_ids[0], "second": business_ids[1]},
        ).all()
        by_role = {}
        for row in grants:
            by_role.setdefault((row.business_id, row.name, row.is_system), set())
            if row.code:
                by_role[(row.business_id, row.name, row.is_system)].add(row.code)
        for business_id in business_ids:
            assert by_role[(business_id, "Owner", True)] == set(TARGETS)
            assert by_role[(business_id, "Admin", True)] == set(TARGETS)
            assert by_role[(business_id, "Manager", True)] == set()
            assert by_role[(business_id, "Employee", True)] == set()
        assert by_role[(business_ids[0], "Backfill custom", False)] == {"inventory.adjust"}
        assert connection.scalar(
            text(
                "SELECT count(*) FROM permissions WHERE code NOT IN "
                "('inventory.adjust','payments.create','payments.update')"
            )
        ) == unrelated_permission_count
        assert connection.scalar(
            text(
                "SELECT count(*) FROM role_permissions rp JOIN permissions p "
                "ON p.id=rp.permission_id WHERE p.code NOT IN "
                "('inventory.adjust','payments.create','payments.update')"
            )
        ) == unrelated_link_count

        link_count = connection.scalar(
            text(
                "SELECT count(*) FROM role_permissions rp JOIN permissions p "
                "ON p.id=rp.permission_id WHERE p.code IN "
                "('inventory.adjust','payments.create','payments.update')"
            )
        )
        command.downgrade(config, "0010_audit_logs")
        command.upgrade(config, "head")
        assert connection.scalar(
            text(
                "SELECT count(*) FROM role_permissions rp JOIN permissions p "
                "ON p.id=rp.permission_id WHERE p.code IN "
                "('inventory.adjust','payments.create','payments.update')"
            )
        ) == link_count
