"""Product management, supplier associations, and tenant integrity.

Revision ID: 0005_products
Revises: 0004_suppliers
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0005_products"
down_revision = "0004_suppliers"
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
    op.create_table("products", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("deleted_at", sa.DateTime(timezone=True)),
                    sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("name", sa.String(160), nullable=False), sa.Column("sku", sa.String(64), nullable=False), sa.Column("barcode", sa.String(128)),
                    sa.Column("description", sa.String(4000)), sa.Column("category", sa.String(100)), sa.Column("brand", sa.String(100)),
                    sa.Column("unit_of_measure", sa.String(32), nullable=False, server_default="piece"), sa.Column("selling_price", sa.Numeric(14, 2), nullable=False, server_default="0"),
                    sa.Column("cost_price", sa.Numeric(14, 2)), sa.Column("tax_rate", sa.Numeric(5, 2)), sa.Column("track_inventory", sa.Boolean(), nullable=False, server_default=sa.true()),
                    sa.Column("reorder_level", sa.Numeric(14, 3)), sa.Column("notes", sa.String(4000)), sa.Column("status", sa.String(16), nullable=False, server_default="active"),
                    sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_products_status"), sa.CheckConstraint("selling_price >= 0", name="ck_products_selling_price"),
                    sa.CheckConstraint("cost_price IS NULL OR cost_price >= 0", name="ck_products_cost_price"), sa.CheckConstraint("tax_rate IS NULL OR (tax_rate >= 0 AND tax_rate <= 100)", name="ck_products_tax_rate"),
                    sa.CheckConstraint("reorder_level IS NULL OR reorder_level >= 0", name="ck_products_reorder_level"),
                    sa.UniqueConstraint("business_id", "sku", name="uq_products_business_sku"), sa.UniqueConstraint("business_id", "barcode", name="uq_products_business_barcode"),
                    sa.UniqueConstraint("business_id", "id", name="uq_products_business_id"))
    for name, columns in (("ix_products_business_status", ["business_id", "status"]), ("ix_products_business_name", ["business_id", "name"]), ("ix_products_business_category", ["business_id", "category"]), ("ix_products_business_created", ["business_id", "created_at"])):
        op.create_index(name, "products", columns)
    op.create_index("uq_suppliers_business_id", "suppliers", ["business_id", "id"], unique=True)
    op.create_table("product_suppliers", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("deleted_at", sa.DateTime(timezone=True)),
                    sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False), sa.Column("product_id", sa.Uuid(), nullable=False), sa.Column("supplier_id", sa.Uuid(), nullable=False),
                    sa.Column("supplier_sku", sa.String(64)), sa.Column("purchase_cost", sa.Numeric(14, 2)), sa.Column("lead_time_days", sa.Integer()), sa.Column("minimum_order_quantity", sa.Numeric(14, 3)), sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
                    sa.ForeignKeyConstraint(["business_id", "product_id"], ["products.business_id", "products.id"], ondelete="RESTRICT"),
                    sa.ForeignKeyConstraint(["business_id", "supplier_id"], ["suppliers.business_id", "suppliers.id"], ondelete="RESTRICT"),
                    sa.UniqueConstraint("product_id", "supplier_id", name="uq_product_suppliers_product_supplier"),
                    sa.CheckConstraint("purchase_cost IS NULL OR purchase_cost >= 0", name="ck_product_suppliers_purchase_cost"), sa.CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_product_suppliers_lead_time"), sa.CheckConstraint("minimum_order_quantity IS NULL OR minimum_order_quantity > 0", name="ck_product_suppliers_minimum_quantity"))
    for name, columns in (("ix_product_suppliers_business", ["business_id"]), ("ix_product_suppliers_product", ["product_id"]), ("ix_product_suppliers_supplier", ["supplier_id"]), ("ix_product_suppliers_primary", ["product_id", "is_primary"])):
        op.create_index(name, "product_suppliers", columns)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE UNIQUE INDEX uq_product_suppliers_one_primary ON product_suppliers (product_id) WHERE is_primary AND deleted_at IS NULL")
        op.execute("""CREATE FUNCTION prevent_product_tenant_move() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF OLD.business_id IS DISTINCT FROM NEW.business_id THEN RAISE EXCEPTION 'Product tenant cannot be changed' USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
        op.execute("CREATE TRIGGER products_immutable_tenant BEFORE UPDATE OF business_id ON products FOR EACH ROW EXECUTE FUNCTION prevent_product_tenant_move()")
        op.execute("""CREATE FUNCTION prevent_product_supplier_tenant_move() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF OLD.business_id IS DISTINCT FROM NEW.business_id THEN RAISE EXCEPTION 'Product supplier tenant cannot be changed' USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
        op.execute("CREATE TRIGGER product_suppliers_immutable_tenant BEFORE UPDATE OF business_id ON product_suppliers FOR EACH ROW EXECUTE FUNCTION prevent_product_supplier_tenant_move()")
    _seed_permission("products.deactivate", "Deactivate products")
    _seed_permission("products.manage_suppliers", "Manage product suppliers")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER product_suppliers_immutable_tenant ON product_suppliers"); op.execute("DROP FUNCTION prevent_product_supplier_tenant_move()")
        op.execute("DROP TRIGGER products_immutable_tenant ON products"); op.execute("DROP FUNCTION prevent_product_tenant_move()")
    op.drop_table("product_suppliers"); op.drop_index("uq_suppliers_business_id", table_name="suppliers"); op.drop_table("products")
    for code in ("products.manage_suppliers", "products.deactivate"):
        permission_id = bind.scalar(sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code})
        if permission_id:
            bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :id"), {"id": permission_id}); bind.execute(sa.text("DELETE FROM permissions WHERE id = :id"), {"id": permission_id})
