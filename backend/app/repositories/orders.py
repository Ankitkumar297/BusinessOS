from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Business, Order, OrderItem


class OrderRepository:
    def __init__(self, db: Session, business_id: UUID) -> None:
        self.db, self.business_id = db, business_id

    def lock_business(self) -> None:
        self.db.execute(select(Business.id).where(Business.id == self.business_id).with_for_update()).one()

    def query(self) -> Select[tuple[Order]]:
        return select(Order).options(selectinload(Order.items)).where(Order.business_id == self.business_id, Order.deleted_at.is_(None))

    def order(self, order_id: UUID) -> Order | None:
        return self.db.scalar(self.query().where(Order.id == order_id))

    def orders(self, search: str, status: str | None, sort_by: str, sort_direction: str, page: int, size: int) -> tuple[list[Order], int]:
        query = self.query()
        if search:
            term = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(or_(Order.order_number.ilike(term, escape="\\")))
        if status:
            query = query.where(Order.status == status)
        columns = {"order_number": Order.order_number, "order_date": Order.order_date, "created_at": Order.created_at, "updated_at": Order.updated_at, "grand_total": Order.grand_total}
        order = columns[sort_by].asc() if sort_direction == "asc" else columns[sort_by].desc()
        total = self.db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
        return list(self.db.scalars(query.order_by(order, Order.id).offset((page - 1) * size).limit(size)).unique()), total
