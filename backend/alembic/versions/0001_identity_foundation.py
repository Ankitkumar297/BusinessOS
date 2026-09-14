"""identity foundation

Revision ID: 0001_identity
Revises:
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_identity"
down_revision = None
branch_labels = None
depends_on = None


def audit_columns() -> list[sa.Column]:
    return [sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)]


def upgrade() -> None:
    op.create_table("businesses", *audit_columns(), sa.Column("name", sa.String(160), nullable=False), sa.Column("slug", sa.String(80), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_businesses_slug_active", "businesses", ["slug"], unique=True)
    op.create_table("permissions", *audit_columns(), sa.Column("code", sa.String(100), nullable=False), sa.Column("description", sa.String(255), nullable=False), sa.UniqueConstraint("code", name="uq_permissions_code"))
    op.create_table("users", *audit_columns(), sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False), sa.Column("email", sa.String(320), nullable=False), sa.Column("full_name", sa.String(160), nullable=False), sa.Column("password_hash", sa.String(512), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.UniqueConstraint("email", name="uq_users_email"))
    op.create_index("ix_users_business_active", "users", ["business_id", "is_active"])
    op.create_table("roles", *audit_columns(), sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(80), nullable=False), sa.Column("description", sa.String(255)), sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.UniqueConstraint("business_id", "name", name="uq_roles_business_name"))
    op.create_index("ix_roles_business_active", "roles", ["business_id", "is_active"])
    op.create_table("user_roles", sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True), sa.Column("role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True))
    op.create_table("role_permissions", sa.Column("role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True), sa.Column("permission_id", sa.Uuid(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True))
    op.create_table("refresh_tokens", *audit_columns(), sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("token_hash", sa.String(64), nullable=False, unique=True), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("user_agent", sa.String(512)))
    op.create_index("ix_refresh_tokens_user_active", "refresh_tokens", ["user_id", "revoked_at", "expires_at"])


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("permissions")
    op.drop_table("businesses")
