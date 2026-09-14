"""Supplier management and tenant ownership protection.

Revision ID: 0004_suppliers
Revises: 0003_customers
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0004_suppliers"
down_revision = "0003_customers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("suppliers", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
                    sa.Column("deleted_at", sa.DateTime(timezone=True)),
                    sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("supplier_name", sa.String(160), nullable=False), sa.Column("company_name", sa.String(160)),
                    sa.Column("supplier_code", sa.String(50)), sa.Column("tax_id", sa.String(100)),
                    sa.Column("registration_number", sa.String(100)), sa.Column("contact_person_name", sa.String(160)),
                    sa.Column("email", sa.String(320)), sa.Column("phone", sa.String(40)), sa.Column("alternate_phone", sa.String(40)),
                    sa.Column("address_line_1", sa.String(160)), sa.Column("address_line_2", sa.String(160)),
                    sa.Column("city", sa.String(100)), sa.Column("state", sa.String(100)), sa.Column("postal_code", sa.String(32)),
                    sa.Column("country", sa.String(100)), sa.Column("payment_terms", sa.String(100)),
                    sa.Column("lead_time_days", sa.Integer()), sa.Column("minimum_order_value", sa.Numeric(14, 2)),
                    sa.Column("currency", sa.String(3)), sa.Column("notes", sa.String(4000)),
                    sa.Column("status", sa.String(16), nullable=False, server_default="active"),
                    sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_suppliers_status"),
                    sa.CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_suppliers_lead_time"),
                    sa.CheckConstraint("minimum_order_value IS NULL OR minimum_order_value >= 0", name="ck_suppliers_minimum_order"),
                    sa.UniqueConstraint("business_id", "supplier_code", name="uq_suppliers_business_code"))
    op.create_index("ix_suppliers_business_status", "suppliers", ["business_id", "status"])
    op.create_index("ix_suppliers_business_name", "suppliers", ["business_id", "supplier_name"])
    op.create_index("ix_suppliers_business_email", "suppliers", ["business_id", "email"])
    op.create_index("ix_suppliers_business_created", "suppliers", ["business_id", "created_at"])
    bind = op.get_bind()
    permissions = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()), sa.column("description", sa.String()))
    links = sa.table("role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission_id", sa.Uuid()))
    roles = sa.table("roles", sa.column("id", sa.Uuid()), sa.column("name", sa.String()), sa.column("is_system", sa.Boolean()))
    code = "suppliers.deactivate"; permission_id = bind.scalar(sa.select(permissions.c.id).where(permissions.c.code == code))
    if permission_id is None:
        permission_id = uuid4(); bind.execute(permissions.insert().values(id=permission_id, code=code, description="Deactivate suppliers"))
    for role_id in bind.scalars(sa.select(roles.c.id).where(roles.c.is_system.is_(True), roles.c.name.in_(("Owner", "Admin")))):
        if not bind.scalar(sa.select(links.c.role_id).where(links.c.role_id == role_id, links.c.permission_id == permission_id)):
            bind.execute(links.insert().values(role_id=role_id, permission_id=permission_id))
    if bind.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION prevent_supplier_tenant_move() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.business_id IS DISTINCT FROM NEW.business_id THEN
            RAISE EXCEPTION 'Supplier tenant cannot be changed' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
        op.execute("CREATE TRIGGER suppliers_immutable_tenant BEFORE UPDATE OF business_id ON suppliers FOR EACH ROW EXECUTE FUNCTION prevent_supplier_tenant_move()")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER suppliers_immutable_tenant ON suppliers")
        op.execute("DROP FUNCTION prevent_supplier_tenant_move()")
    permission_id = bind.scalar(sa.text("SELECT id FROM permissions WHERE code = 'suppliers.deactivate'"))
    if permission_id:
        bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :id"), {"id": permission_id})
        bind.execute(sa.text("DELETE FROM permissions WHERE id = :id"), {"id": permission_id})
    op.drop_table("suppliers")
