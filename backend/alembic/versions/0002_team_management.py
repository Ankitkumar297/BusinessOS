"""Team permissions and database-enforced tenant consistency.

Revision ID: 0002_team
Revises: 0001_identity
"""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = "0002_team"
down_revision = "0001_identity"
branch_labels = None
depends_on = None

# Snapshot the catalog; migrations must not depend on future application definitions.
GROUPS = {
    "users": ["view", "create", "update", "deactivate", "delete", "assign_roles"],
    "roles": ["view", "create", "update", "delete", "assign_permissions"],
    "customers": ["view", "create", "update", "delete"],
    "products": ["view", "create", "update", "delete"],
    "suppliers": ["view", "create", "update", "delete"],
    "inventory": ["view", "manage"], "orders": ["view", "create", "update", "cancel"],
    "payments": ["view", "manage"], "invoices": ["view", "create", "update", "issue"],
    "reports": ["view"], "settings": ["view", "manage"],
}


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
    if bind.dialect.name == "postgresql":
        # Refuse to silently retain any existing corrupt cross-tenant assignments.
        invalid = bind.execute(sa.text("SELECT count(*) FROM user_roles ur JOIN users u ON u.id=ur.user_id JOIN roles r ON r.id=ur.role_id WHERE u.business_id<>r.business_id")).scalar()
        if invalid:
            raise RuntimeError("Cross-tenant assignments found; reconcile them before migrating.")
        op.execute("""CREATE FUNCTION enforce_user_role_tenant() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM users u JOIN roles r ON r.business_id=u.business_id
                         WHERE u.id=NEW.user_id AND r.id=NEW.role_id) THEN
            RAISE EXCEPTION 'User and role must belong to the same business' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
        op.execute("CREATE TRIGGER user_roles_tenant BEFORE INSERT OR UPDATE ON user_roles FOR EACH ROW EXECUTE FUNCTION enforce_user_role_tenant()")
        op.execute("""CREATE FUNCTION prevent_identity_tenant_move() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.business_id IS DISTINCT FROM NEW.business_id THEN
            RAISE EXCEPTION 'Identity tenant cannot be changed' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
        for table in ("users", "roles"):
            op.execute(f"CREATE TRIGGER {table}_immutable_tenant BEFORE UPDATE OF business_id ON {table} FOR EACH ROW EXECUTE FUNCTION prevent_identity_tenant_move()")
    permissions = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()), sa.column("description", sa.String()))
    roles = sa.table("roles", sa.column("id", sa.Uuid()), sa.column("name", sa.String()), sa.column("is_system", sa.Boolean()))
    links = sa.table("role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission_id", sa.Uuid()))
    existing = dict(bind.execute(sa.select(permissions.c.code, permissions.c.id)).all())
    new_codes = []
    for group, actions in GROUPS.items():
        for action in actions:
            code = f"{group}.{action}"
            new_codes.append(code)
            if code not in existing:
                existing[code] = uuid4()
                bind.execute(permissions.insert().values(id=existing[code], code=code, description=f"{action.replace('_', ' ').capitalize()} {group}"))
    for role_id, name in bind.execute(sa.select(roles.c.id, roles.c.name).where(roles.c.is_system.is_(True))):
        assigned = set(bind.scalars(sa.select(links.c.permission_id).where(links.c.role_id == role_id)))
        for code in new_codes:
            allowed = name == "Owner" or (name == "Admin" and code != "settings.manage") or (name == "Manager" and code.endswith(".view"))
            if allowed and existing[code] not in assigned:
                bind.execute(links.insert().values(role_id=role_id, permission_id=existing[code]))


def downgrade() -> None:
    op.drop_column("users", "auth_version")
    # Retain permission data to avoid destroying custom role grants on rollback.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER user_roles_tenant ON user_roles")
        for table in ("users", "roles"):
            op.execute(f"DROP TRIGGER {table}_immutable_tenant ON {table}")
        op.execute("DROP FUNCTION enforce_user_role_tenant()")
        op.execute("DROP FUNCTION prevent_identity_tenant_move()")
