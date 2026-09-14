"""Backfill inventory and payment write permissions for existing system roles.

Revision ID: 0011_permission_backfill
Revises: 0010_audit_logs
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0011_permission_backfill"
down_revision = "0010_audit_logs"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "inventory.adjust": "Adjust inventory",
    "payments.create": "Create payments",
    "payments.update": "Update payments",
}
SYSTEM_ROLES = {"Owner", "Admin"}


def upgrade() -> None:
    bind = op.get_bind()
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

    permission_ids = {}
    for code, description in PERMISSIONS.items():
        permission_id = bind.execute(
            sa.select(permissions.c.id).where(permissions.c.code == code)
        ).scalar_one_or_none()
        if permission_id is None:
            permission_id = uuid4()
            bind.execute(
                permissions.insert().values(
                    id=permission_id,
                    code=code,
                    description=description,
                )
            )
        permission_ids[code] = permission_id

    system_role_ids = bind.execute(
        sa.select(roles.c.id).where(
            roles.c.is_system.is_(True),
            roles.c.name.in_(SYSTEM_ROLES),
        )
    ).scalars()
    for role_id in system_role_ids:
        for permission_id in permission_ids.values():
            already_granted = bind.execute(
                sa.select(links.c.role_id).where(
                    links.c.role_id == role_id,
                    links.c.permission_id == permission_id,
                )
            ).first()
            if already_granted is None:
                bind.execute(
                    links.insert().values(
                        role_id=role_id,
                        permission_id=permission_id,
                    )
                )


def downgrade() -> None:
    # Retain permission definitions and grants to avoid revoking existing access
    # or destroying links that may subsequently have been assigned intentionally.
    pass
