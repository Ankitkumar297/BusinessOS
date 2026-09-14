from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import Business, Supplier


class SupplierRepository:
    def __init__(self, db: Session, business_id: UUID) -> None:
        self.db, self.business_id = db, business_id

    def lock_business(self) -> None:
        self.db.execute(select(Business.id).where(Business.id == self.business_id).with_for_update()).one()

    def query(self) -> Select[tuple[Supplier]]:
        return select(Supplier).where(Supplier.business_id == self.business_id, Supplier.deleted_at.is_(None))

    def supplier(self, supplier_id: UUID) -> Supplier | None:
        return self.db.scalar(self.query().where(Supplier.id == supplier_id))

    def suppliers(self, search: str, status: str | None, country: str | None, sort_by: str,
                  sort_direction: str, page: int, size: int) -> tuple[list[Supplier], int]:
        query = self.query()
        if search:
            term = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(or_(Supplier.supplier_name.ilike(term, escape="\\"),
                                    Supplier.company_name.ilike(term, escape="\\"), Supplier.supplier_code.ilike(term, escape="\\"),
                                    Supplier.contact_person_name.ilike(term, escape="\\"), Supplier.email.ilike(term, escape="\\"),
                                    Supplier.phone.ilike(term, escape="\\")))
        if status:
            query = query.where(Supplier.status == status)
        if country:
            query = query.where(Supplier.country.ilike(country.strip()))
        columns = {"name": Supplier.supplier_name, "supplier_code": Supplier.supplier_code,
                   "created_at": Supplier.created_at, "updated_at": Supplier.updated_at}
        ordering = columns[sort_by].asc() if sort_direction == "asc" else columns[sort_by].desc()
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.scalars(query.order_by(ordering, Supplier.id).offset((page - 1) * size).limit(size))
        return list(rows), total
