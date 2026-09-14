"""Customer management and customer permission lifecycle.

Revision ID: 0003_customers
Revises: 0002_team
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0003_customers"
down_revision = "0002_team"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_type", sa.String(16), nullable=False, server_default="individual"),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("company_name", sa.String(160)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(40)),
        sa.Column("alternate_phone", sa.String(40)),
        sa.Column("address_line_1", sa.String(160)),
        sa.Column("address_line_2", sa.String(160)),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(100)),
        sa.Column("postal_code", sa.String(32)),
        sa.Column("country", sa.String(100)),
        sa.Column("tax_id", sa.String(100)),
        sa.Column("notes", sa.String(4000)),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.CheckConstraint("customer_type IN ('individual', 'business')", name="ck_customers_type"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_customers_status"),
    )
    op.create_index("ix_customers_business_status", "customers", ["business_id", "status"])
    op.create_index("ix_customers_business_name", "customers", ["business_id", "display_name"])
    op.create_index("ix_customers_business_email", "customers", ["business_id", "email"])
    op.create_index("ix_customers_business_created", "customers", ["business_id", "created_at"])

    bind = op.get_bind()
    permissions = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()), sa.column("description", sa.String()))
    role_permissions = sa.table("role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission_id", sa.Uuid()))
    roles = sa.table("roles", sa.column("id", sa.Uuid()), sa.column("name", sa.String()), sa.column("is_system", sa.Boolean()))
    code = "customers.deactivate"
    permission_id = bind.scalar(sa.select(permissions.c.id).where(permissions.c.code == code))
    if permission_id is None:
        permission_id = uuid4()
        bind.execute(permissions.insert().values(id=permission_id, code=code, description="Deactivate customers"))
    for role_id in bind.scalars(sa.select(roles.c.id).where(roles.c.is_system.is_(True), roles.c.name.in_(("Owner", "Admin")))):
        exists = bind.scalar(sa.select(role_permissions.c.role_id).where(role_permissions.c.role_id == role_id, role_permissions.c.permission_id == permission_id))
        if not exists:
            bind.execute(role_permissions.insert().values(role_id=role_id, permission_id=permission_id))

    if bind.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION prevent_customer_tenant_move() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.business_id IS DISTINCT FROM NEW.business_id THEN
            RAISE EXCEPTION 'Customer tenant cannot be changed' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
        op.execute("CREATE TRIGGER customers_immutable_tenant BEFORE UPDATE OF business_id ON customers FOR EACH ROW EXECUTE FUNCTION prevent_customer_tenant_move()")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER customers_immutable_tenant ON customers")
        op.execute("DROP FUNCTION prevent_customer_tenant_move()")
    permission_id = bind.scalar(sa.text("SELECT id FROM permissions WHERE code = 'customers.deactivate'"))
    if permission_id:
        bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :id"), {"id": permission_id})
        bind.execute(sa.text("DELETE FROM permissions WHERE id = :id"), {"id": permission_id})
    op.drop_table("customers")
