from datetime import datetime
from uuid import UUID

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Table, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDTimestampSoftDeleteModel

user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Business(UUIDTimestampSoftDeleteModel):
    __tablename__ = "businesses"
    __table_args__ = (Index("ix_businesses_slug_active", "slug", unique=True),)

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    users: Mapped[list["User"]] = relationship(back_populates="business")
    roles: Mapped[list["Role"]] = relationship(back_populates="business")
    customers: Mapped[list["Customer"]] = relationship(back_populates="business")
    suppliers: Mapped[list["Supplier"]] = relationship(back_populates="business")
    products: Mapped[list["Product"]] = relationship(back_populates="business")
    inventories: Mapped[list["Inventory"]] = relationship(back_populates="business")
    orders: Mapped[list["Order"]] = relationship(back_populates="business")
    payments: Mapped[list["Payment"]] = relationship(back_populates="business", overlaps="order,payments")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="business", overlaps="order,invoices")
    product_suppliers: Mapped[list["ProductSupplier"]] = relationship(back_populates="business", overlaps="product,supplier")


class User(UUIDTimestampSoftDeleteModel):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),
                      UniqueConstraint("business_id", "id", name="uq_users_business_id"),
                      Index("ix_users_business_active", "business_id", "is_active"))

    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    business: Mapped[Business] = relationship(back_populates="users")
    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, back_populates="users")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user")


class Role(UUIDTimestampSoftDeleteModel):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_roles_business_name"),
                      Index("ix_roles_business_active", "business_id", "is_active"))

    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    business: Mapped[Business] = relationship(back_populates="roles")
    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, back_populates="roles")


class Permission(UUIDTimestampSoftDeleteModel):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("code", name="uq_permissions_code"),)

    code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    roles: Mapped[list[Role]] = relationship(secondary=role_permissions, back_populates="permissions")


class Customer(UUIDTimestampSoftDeleteModel):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint("customer_type IN ('individual', 'business')", name="ck_customers_type"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_customers_status"),
        Index("ix_customers_business_status", "business_id", "status"),
        Index("ix_customers_business_name", "business_id", "display_name"),
        Index("ix_customers_business_email", "business_id", "email"),
        Index("ix_customers_business_created", "business_id", "created_at"),
    )

    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    customer_type: Mapped[str] = mapped_column(String(16), nullable=False, default="individual")
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    alternate_phone: Mapped[str | None] = mapped_column(String(40))
    address_line_1: Mapped[str | None] = mapped_column(String(160))
    address_line_2: Mapped[str | None] = mapped_column(String(160))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(100))
    tax_id: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    business: Mapped[Business] = relationship(back_populates="customers")


class Supplier(UUIDTimestampSoftDeleteModel):
    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_suppliers_status"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_suppliers_lead_time"),
        CheckConstraint("minimum_order_value IS NULL OR minimum_order_value >= 0", name="ck_suppliers_minimum_order"),
        UniqueConstraint("business_id", "supplier_code", name="uq_suppliers_business_code"),
        UniqueConstraint("business_id", "id", name="uq_suppliers_business_id"),
        Index("ix_suppliers_business_status", "business_id", "status"),
        Index("ix_suppliers_business_name", "business_id", "supplier_name"),
        Index("ix_suppliers_business_email", "business_id", "email"),
        Index("ix_suppliers_business_created", "business_id", "created_at"),
    )

    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(160), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(160))
    supplier_code: Mapped[str | None] = mapped_column(String(50))
    tax_id: Mapped[str | None] = mapped_column(String(100))
    registration_number: Mapped[str | None] = mapped_column(String(100))
    contact_person_name: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    alternate_phone: Mapped[str | None] = mapped_column(String(40))
    address_line_1: Mapped[str | None] = mapped_column(String(160))
    address_line_2: Mapped[str | None] = mapped_column(String(160))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(100))
    payment_terms: Mapped[str | None] = mapped_column(String(100))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    minimum_order_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    notes: Mapped[str | None] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    business: Mapped[Business] = relationship(back_populates="suppliers")
    product_links: Mapped[list["ProductSupplier"]] = relationship(back_populates="supplier", overlaps="business,product,product_suppliers,supplier_links")


class Product(UUIDTimestampSoftDeleteModel):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_products_status"),
        CheckConstraint("selling_price >= 0", name="ck_products_selling_price"),
        CheckConstraint("cost_price IS NULL OR cost_price >= 0", name="ck_products_cost_price"),
        CheckConstraint("tax_rate IS NULL OR (tax_rate >= 0 AND tax_rate <= 100)", name="ck_products_tax_rate"),
        CheckConstraint("reorder_level IS NULL OR reorder_level >= 0", name="ck_products_reorder_level"),
        UniqueConstraint("business_id", "sku", name="uq_products_business_sku"),
        UniqueConstraint("business_id", "barcode", name="uq_products_business_barcode"),
        UniqueConstraint("business_id", "id", name="uq_products_business_id"),
        Index("ix_products_business_status", "business_id", "status"), Index("ix_products_business_name", "business_id", "name"),
        Index("ix_products_business_category", "business_id", "category"), Index("ix_products_business_created", "business_id", "created_at"),
    )
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(4000))
    category: Mapped[str | None] = mapped_column(String(100))
    brand: Mapped[str | None] = mapped_column(String(100))
    unit_of_measure: Mapped[str] = mapped_column(String(32), nullable=False, default="piece")
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    track_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reorder_level: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    notes: Mapped[str | None] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    business: Mapped[Business] = relationship(back_populates="products")
    supplier_links: Mapped[list["ProductSupplier"]] = relationship(back_populates="product", overlaps="business,product_links,product_suppliers,supplier")
    inventory: Mapped["Inventory | None"] = relationship(back_populates="product", uselist=False)
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product", overlaps="items,order")


class ProductSupplier(UUIDTimestampSoftDeleteModel):
    __tablename__ = "product_suppliers"
    __table_args__ = (
        ForeignKeyConstraint(["business_id", "product_id"], ["products.business_id", "products.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["business_id", "supplier_id"], ["suppliers.business_id", "suppliers.id"], ondelete="RESTRICT"),
        UniqueConstraint("product_id", "supplier_id", name="uq_product_suppliers_product_supplier"),
        CheckConstraint("purchase_cost IS NULL OR purchase_cost >= 0", name="ck_product_suppliers_purchase_cost"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_product_suppliers_lead_time"),
        CheckConstraint("minimum_order_quantity IS NULL OR minimum_order_quantity > 0", name="ck_product_suppliers_minimum_quantity"),
        Index("ix_product_suppliers_business", "business_id"), Index("ix_product_suppliers_product", "product_id"),
        Index("ix_product_suppliers_supplier", "supplier_id"), Index("ix_product_suppliers_primary", "product_id", "is_primary"),
    )
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(nullable=False)
    supplier_sku: Mapped[str | None] = mapped_column(String(64))
    purchase_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    minimum_order_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    business: Mapped[Business] = relationship(back_populates="product_suppliers", overlaps="product,supplier")
    product: Mapped[Product] = relationship(back_populates="supplier_links", overlaps="business,product_links,product_suppliers,supplier")
    supplier: Mapped[Supplier] = relationship(back_populates="product_links", overlaps="business,product,product_suppliers,supplier_links")


class Inventory(UUIDTimestampSoftDeleteModel):
    __tablename__ = "inventories"
    __table_args__ = (UniqueConstraint("business_id", "product_id", name="uq_inventories_business_product"), UniqueConstraint("business_id", "id", name="uq_inventories_business_id"), CheckConstraint("quantity_on_hand >= 0", name="ck_inventories_nonnegative"), Index("ix_inventories_business_quantity", "business_id", "quantity_on_hand"))
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal("0"))
    business: Mapped[Business] = relationship(back_populates="inventories")
    product: Mapped[Product] = relationship(back_populates="inventory")
    movements: Mapped[list["StockMovement"]] = relationship(back_populates="inventory")


class StockMovement(UUIDTimestampSoftDeleteModel):
    __tablename__ = "stock_movements"
    __table_args__ = (ForeignKeyConstraint(["business_id", "inventory_id"], ["inventories.business_id", "inventories.id"], ondelete="RESTRICT"), ForeignKeyConstraint(["business_id", "product_id"], ["products.business_id", "products.id"], ondelete="RESTRICT"), CheckConstraint("movement_type IN ('opening_balance','adjustment_in','adjustment_out','correction')", name="ck_stock_movements_type"), Index("ix_stock_movements_business_created", "business_id", "created_at"), Index("ix_stock_movements_inventory", "inventory_id"))
    business_id: Mapped[UUID] = mapped_column(nullable=False)
    inventory_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    quantity_before: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    quantity_after: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(4000))
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    inventory: Mapped[Inventory] = relationship(back_populates="movements")


class Order(UUIDTimestampSoftDeleteModel):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("business_id", "order_number", name="uq_orders_business_number"),
                      UniqueConstraint("business_id", "id", name="uq_orders_business_id"),
                      CheckConstraint("status IN ('draft','confirmed','cancelled')", name="ck_orders_status"),
                      CheckConstraint("subtotal >= 0", name="ck_orders_subtotal"), CheckConstraint("tax_total >= 0", name="ck_orders_tax_total"),
                      CheckConstraint("grand_total >= 0", name="ck_orders_grand_total"), Index("ix_orders_business_status", "business_id", "status"),
                      Index("ix_orders_business_date", "business_id", "order_date"), Index("ix_orders_business_created", "business_id", "created_at"))
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    order_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    notes: Mapped[str | None] = mapped_column(String(4000))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    business: Mapped[Business] = relationship(back_populates="orders")
    customer: Mapped[Customer] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan", overlaps="product,order_items")
    payments: Mapped[list["Payment"]] = relationship(back_populates="order", overlaps="business,payments")
    invoice: Mapped["Invoice | None"] = relationship(back_populates="order", uselist=False, overlaps="business,invoices")


class Payment(UUIDTimestampSoftDeleteModel):
    __tablename__ = "payments"
    __table_args__ = (ForeignKeyConstraint(["business_id", "order_id"], ["orders.business_id", "orders.id"], ondelete="RESTRICT"), UniqueConstraint("business_id", "payment_number", name="uq_payments_business_number"), CheckConstraint("amount > 0", name="ck_payments_amount"), CheckConstraint("payment_method IN ('cash','card','bank_transfer','upi','other')", name="ck_payments_method"), CheckConstraint("status IN ('pending','completed','failed','cancelled')", name="ck_payments_status"), Index("ix_payments_business_order", "business_id", "order_id"), Index("ix_payments_business_date", "business_id", "paid_at"))
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    order_id: Mapped[UUID] = mapped_column(nullable=False)
    payment_number: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    external_reference: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(String(4000))
    business: Mapped[Business] = relationship(back_populates="payments", overlaps="order,payments")
    order: Mapped[Order] = relationship(back_populates="payments", overlaps="business,payments")


class Invoice(UUIDTimestampSoftDeleteModel):
    __tablename__ = "invoices"
    __table_args__ = (
        ForeignKeyConstraint(["business_id", "order_id"], ["orders.business_id", "orders.id"], ondelete="RESTRICT"),
        UniqueConstraint("business_id", "invoice_number", name="uq_invoices_business_number"),
        UniqueConstraint("business_id", "order_id", name="uq_invoices_business_order"),
        UniqueConstraint("business_id", "id", name="uq_invoices_business_id"),
        CheckConstraint("status IN ('issued')", name="ck_invoices_status"),
        CheckConstraint("subtotal >= 0", name="ck_invoices_subtotal"),
        CheckConstraint("tax_total >= 0", name="ck_invoices_tax_total"),
        CheckConstraint("grand_total >= 0", name="ck_invoices_grand_total"),
        Index("ix_invoices_business_status", "business_id", "status"),
        Index("ix_invoices_business_issued", "business_id", "issued_at"),
        Index("ix_invoices_business_customer", "business_id", "customer_name"),
    )
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    order_id: Mapped[UUID] = mapped_column(nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="issued")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_email: Mapped[str | None] = mapped_column(String(320))
    customer_address: Mapped[str | None] = mapped_column(String(1000))
    customer_tax_id: Mapped[str | None] = mapped_column(String(100))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    business: Mapped[Business] = relationship(back_populates="invoices", overlaps="order,invoice")
    order: Mapped[Order] = relationship(back_populates="invoice", overlaps="business,invoices")
    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(UUIDTimestampSoftDeleteModel):
    __tablename__ = "invoice_items"
    __table_args__ = (
        ForeignKeyConstraint(["business_id", "invoice_id"], ["invoices.business_id", "invoices.id"], ondelete="RESTRICT"),
        CheckConstraint("quantity > 0", name="ck_invoice_items_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_invoice_items_unit_price"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_invoice_items_tax_rate"),
        CheckConstraint("line_subtotal >= 0", name="ck_invoice_items_subtotal"),
        CheckConstraint("line_tax >= 0", name="ck_invoice_items_tax"),
        CheckConstraint("line_total >= 0", name="ck_invoice_items_total"),
        Index("ix_invoice_items_invoice", "invoice_id"),
    )
    business_id: Mapped[UUID] = mapped_column(nullable=False)
    invoice_id: Mapped[UUID] = mapped_column(nullable=False)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    invoice: Mapped[Invoice] = relationship(back_populates="items")


class OrderItem(UUIDTimestampSoftDeleteModel):
    __tablename__ = "order_items"
    __table_args__ = (ForeignKeyConstraint(["business_id", "order_id"], ["orders.business_id", "orders.id"], ondelete="CASCADE"),
                      ForeignKeyConstraint(["business_id", "product_id"], ["products.business_id", "products.id"], ondelete="RESTRICT"),
                      CheckConstraint("quantity > 0", name="ck_order_items_quantity"), CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price"),
                      CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_order_items_tax_rate"), CheckConstraint("line_subtotal >= 0", name="ck_order_items_subtotal"),
                      CheckConstraint("line_tax >= 0", name="ck_order_items_tax"), CheckConstraint("line_total >= 0", name="ck_order_items_total"),
                      Index("ix_order_items_business_order", "business_id", "order_id"))
    business_id: Mapped[UUID] = mapped_column(nullable=False)
    order_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    order: Mapped[Order] = relationship(back_populates="items", overlaps="product,order_items")
    product: Mapped[Product] = relationship(back_populates="order_items", overlaps="items,order")


class RefreshToken(UUIDTimestampSoftDeleteModel):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_active", "user_id", "revoked_at", "expires_at"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    user: Mapped[User] = relationship(back_populates="refresh_tokens")
