"""Tenant-safe append-only audit log infrastructure.

Revision ID: 0010_audit_logs
Revises: 0009_invoices
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0010_audit_logs"
down_revision = "0009_invoices"
branch_labels = None
depends_on = None

AUDIT_PERMISSION = "audit.view"
AUDIT_DESCRIPTION = "View audit"


def upgrade() -> None:
    bind = op.get_bind()
    op.create_index(
        "uq_users_business_id", "users", ["business_id", "id"], unique=True
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_name_snapshot", sa.String(160), nullable=False),
        sa.Column("actor_email_snapshot", sa.String(320), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("entity_display", sa.String(255), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "actor_user_id"],
            ["users.business_id", "users.id"],
            name="fk_audit_logs_actor_tenant",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_audit_logs_business_created",
        "audit_logs",
        ["business_id", "created_at", "id"],
    )
    op.create_index(
        "ix_audit_logs_business_action_created",
        "audit_logs",
        ["business_id", "action", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_business_entity",
        "audit_logs",
        ["business_id", "entity_type", "entity_id", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_business_actor_created",
        "audit_logs",
        ["business_id", "actor_user_id", "created_at"],
    )

    if bind.dialect.name == "postgresql":
        op.execute(
            """CREATE FUNCTION prevent_audit_log_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'Audit logs are append-only' USING ERRCODE='23514';
            END $$"""
        )
        op.execute(
            "CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs "
            "FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation()"
        )

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("is_system", sa.Boolean()),
    )
    links = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )
    permission_id = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == AUDIT_PERMISSION)
    ).scalar_one_or_none()
    if permission_id is None:
        permission_id = uuid4()
        bind.execute(
            permissions.insert().values(
                id=permission_id,
                code=AUDIT_PERMISSION,
                description=AUDIT_DESCRIPTION,
            )
        )
    for role_id, role_name in bind.execute(
        sa.select(roles.c.id, roles.c.name).where(roles.c.is_system.is_(True))
    ):
        if role_name not in {"Owner", "Admin", "Manager"}:
            continue
        already_granted = bind.execute(
            sa.select(links.c.role_id).where(
                links.c.role_id == role_id,
                links.c.permission_id == permission_id,
            )
        ).first()
        if already_granted is None:
            bind.execute(
                links.insert().values(
                    role_id=role_id, permission_id=permission_id
                )
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER audit_logs_append_only ON audit_logs")
        op.execute("DROP FUNCTION prevent_audit_log_mutation()")
    op.drop_table("audit_logs")
    op.drop_index("uq_users_business_id", table_name="users")
    # Retain audit.view and its role links to avoid destroying custom grants.
