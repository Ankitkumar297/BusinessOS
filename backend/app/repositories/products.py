from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Business, Product, ProductSupplier


class ProductRepository:
    def __init__(self, db: Session, business_id: UUID) -> None:
        self.db, self.business_id = db, business_id

    def lock_business(self) -> None:
        self.db.execute(select(Business.id).where(Business.id == self.business_id).with_for_update()).one()

    def query(self) -> Select[tuple[Product]]:
        return select(Product).options(selectinload(Product.supplier_links).selectinload(ProductSupplier.supplier)).where(
            Product.business_id == self.business_id, Product.deleted_at.is_(None))

    def product(self, product_id: UUID) -> Product | None:
        return self.db.scalar(self.query().where(Product.id == product_id))

    def products(self, search: str, status: str | None, category: str | None, track_inventory: bool | None,
                 supplier_id: UUID | None, sort_by: str, sort_direction: str, page: int, size: int) -> tuple[list[Product], int]:
        query = self.query()
        if search:
            term = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(or_(Product.name.ilike(term, escape="\\"), Product.sku.ilike(term, escape="\\"),
                                    Product.barcode.ilike(term, escape="\\"), Product.brand.ilike(term, escape="\\"),
                                    Product.category.ilike(term, escape="\\")))
        if status:
            query = query.where(Product.status == status)
        if category:
            query = query.where(Product.category.ilike(category.strip()))
        if track_inventory is not None:
            query = query.where(Product.track_inventory == track_inventory)
        if supplier_id:
            query = query.join(ProductSupplier, ProductSupplier.product_id == Product.id).where(
                ProductSupplier.business_id == self.business_id, ProductSupplier.deleted_at.is_(None), ProductSupplier.supplier_id == supplier_id)
        columns = {"name": Product.name, "sku": Product.sku, "category": Product.category,
                   "selling_price": Product.selling_price, "created_at": Product.created_at, "updated_at": Product.updated_at}
        order = columns[sort_by].asc() if sort_direction == "asc" else columns[sort_by].desc()
        total = self.db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
        rows = self.db.scalars(query.order_by(order, Product.id).offset((page - 1) * size).limit(size)).unique()
        return list(rows), total

    def links(self, product_id: UUID) -> list[ProductSupplier]:
        return list(self.db.scalars(select(ProductSupplier).options(selectinload(ProductSupplier.supplier)).where(
            ProductSupplier.business_id == self.business_id, ProductSupplier.product_id == product_id,
            ProductSupplier.deleted_at.is_(None))))

    def link(self, product_id: UUID, supplier_id: UUID) -> ProductSupplier | None:
        return self.db.scalar(select(ProductSupplier).options(selectinload(ProductSupplier.supplier)).where(
            ProductSupplier.business_id == self.business_id, ProductSupplier.product_id == product_id,
            ProductSupplier.supplier_id == supplier_id, ProductSupplier.deleted_at.is_(None)))
