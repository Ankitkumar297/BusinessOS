from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import Business, Customer


class CustomerRepository:
    def __init__(self, db: Session, business_id: UUID) -> None:
        self.db, self.business_id = db, business_id

    def lock_business(self) -> None:
        self.db.execute(select(Business.id).where(Business.id == self.business_id).with_for_update()).one()

    def query(self) -> Select[tuple[Customer]]:
        return select(Customer).where(Customer.business_id == self.business_id, Customer.deleted_at.is_(None))

    def customer(self, customer_id: UUID) -> Customer | None:
        return self.db.scalar(self.query().where(Customer.id == customer_id))

    def customers(self, search: str, status: str | None, customer_type: str | None, sort_by: str,
                  sort_direction: str, page: int, size: int) -> tuple[list[Customer], int]:
        query = self.query()
        if search:
            term = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(or_(Customer.display_name.ilike(term, escape="\\"),
                                    Customer.company_name.ilike(term, escape="\\"),
                                    Customer.email.ilike(term, escape="\\"),
                                    Customer.phone.ilike(term, escape="\\")))
        if status:
            query = query.where(Customer.status == status)
        if customer_type:
            query = query.where(Customer.customer_type == customer_type)
        columns = {"name": Customer.display_name, "created_at": Customer.created_at, "updated_at": Customer.updated_at}
        ordering = columns[sort_by].asc() if sort_direction == "asc" else columns[sort_by].desc()
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.scalars(query.order_by(ordering, Customer.id).offset((page - 1) * size).limit(size))
        return list(rows), total
