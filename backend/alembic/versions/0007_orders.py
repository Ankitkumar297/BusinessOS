"""Tenant-safe orders and immutable historical order lines.

Revision ID: 0007_orders
Revises: 0006_inventory
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0007_orders"
down_revision = "0006_inventory"
branch_labels = None
depends_on = None


def _seed_permission(code: str, description: str) -> None:
    bind = op.get_bind()
    permissions = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()), sa.column("description", sa.String()))
    links = sa.table("role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission_id", sa.Uuid()))
    roles = sa.table("roles", sa.column("id", sa.Uuid()), sa.column("name", sa.String()), sa.column("is_system", sa.Boolean()))
    permission_id = bind.scalar(sa.select(permissions.c.id).where(permissions.c.code == code))
    if permission_id is None:
        permission_id = uuid4(); bind.execute(permissions.insert().values(id=permission_id, code=code, description=description))
    for role_id in bind.scalars(sa.select(roles.c.id).where(roles.c.is_system.is_(True), roles.c.name.in_(("Owner", "Admin")))):
        if not bind.scalar(sa.select(links.c.role_id).where(links.c.role_id == role_id, links.c.permission_id == permission_id)):
            bind.execute(links.insert().values(role_id=role_id, permission_id=permission_id))


def upgrade() -> None:
    op.create_table("orders",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False), sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_number", sa.String(64), nullable=False), sa.Column("status", sa.String(16), server_default="draft", nullable=False), sa.Column("order_date", sa.DateTime(timezone=True), nullable=False), sa.Column("notes", sa.String(4000)),
        sa.Column("subtotal", sa.Numeric(14, 2), server_default="0", nullable=False), sa.Column("tax_total", sa.Numeric(14, 2), server_default="0", nullable=False), sa.Column("grand_total", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.UniqueConstraint("business_id", "order_number", name="uq_orders_business_number"), sa.UniqueConstraint("business_id", "id", name="uq_orders_business_id"), sa.CheckConstraint("status IN ('draft','confirmed','cancelled')", name="ck_orders_status"),
        sa.CheckConstraint("subtotal >= 0", name="ck_orders_subtotal"), sa.CheckConstraint("tax_total >= 0", name="ck_orders_tax_total"), sa.CheckConstraint("grand_total >= 0", name="ck_orders_grand_total"))
    op.create_index("ix_orders_business_status", "orders", ["business_id", "status"]); op.create_index("ix_orders_business_date", "orders", ["business_id", "order_date"]); op.create_index("ix_orders_business_created", "orders", ["business_id", "created_at"])
    op.create_table("order_items",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("business_id", sa.Uuid(), nullable=False), sa.Column("order_id", sa.Uuid(), nullable=False), sa.Column("product_id", sa.Uuid(), nullable=False), sa.Column("product_name", sa.String(160), nullable=False), sa.Column("product_sku", sa.String(64), nullable=False), sa.Column("quantity", sa.Numeric(14, 3), nullable=False), sa.Column("unit_price", sa.Numeric(14, 2), nullable=False), sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0", nullable=False), sa.Column("line_subtotal", sa.Numeric(14, 2), nullable=False), sa.Column("line_tax", sa.Numeric(14, 2), nullable=False), sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        sa.ForeignKeyConstraint(["business_id", "order_id"], ["orders.business_id", "orders.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["business_id", "product_id"], ["products.business_id", "products.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity"), sa.CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price"), sa.CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_order_items_tax_rate"), sa.CheckConstraint("line_subtotal >= 0", name="ck_order_items_subtotal"), sa.CheckConstraint("line_tax >= 0", name="ck_order_items_tax"), sa.CheckConstraint("line_total >= 0", name="ck_order_items_total"))
    op.create_index("ix_order_items_business_order", "order_items", ["business_id", "order_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION enforce_order_tenant() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_TABLE_NAME = 'orders' THEN IF TG_OP = 'UPDATE' AND OLD.business_id IS DISTINCT FROM NEW.business_id THEN RAISE EXCEPTION 'Order tenant cannot be changed'; END IF; IF NOT EXISTS (SELECT 1 FROM customers WHERE id=NEW.customer_id AND business_id=NEW.business_id AND deleted_at IS NULL) THEN RAISE EXCEPTION 'Order customer must belong to its tenant'; END IF; ELSE IF TG_OP = 'UPDATE' AND OLD.business_id IS DISTINCT FROM NEW.business_id THEN RAISE EXCEPTION 'Order item tenant cannot be changed'; END IF; END IF; RETURN NEW; END $$""")
        op.execute("CREATE TRIGGER orders_tenant_guard BEFORE INSERT OR UPDATE OF business_id, customer_id ON orders FOR EACH ROW EXECUTE FUNCTION enforce_order_tenant()")
        op.execute("CREATE TRIGGER order_items_tenant_guard BEFORE UPDATE OF business_id ON order_items FOR EACH ROW EXECUTE FUNCTION enforce_order_tenant()")
    for code, description in (("orders.view", "View orders"), ("orders.create", "Create orders"), ("orders.update", "Update draft orders"), ("orders.confirm", "Confirm orders"), ("orders.cancel", "Cancel draft orders")):
        _seed_permission(code, description)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER order_items_tenant_guard ON order_items"); op.execute("DROP TRIGGER orders_tenant_guard ON orders"); op.execute("DROP FUNCTION enforce_order_tenant()")
    op.drop_table("order_items"); op.drop_table("orders")
    for code in ("orders.cancel", "orders.confirm", "orders.update", "orders.create", "orders.view"):
        permission_id = bind.scalar(sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code})
        if permission_id:
            bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :id"), {"id": permission_id}); bind.execute(sa.text("DELETE FROM permissions WHERE id = :id"), {"id": permission_id})
