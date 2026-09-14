from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models import Customer, Inventory, Order, OrderItem, Payment, Product

ZERO = Decimal("0.00")
MONEY = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or ZERO)).quantize(MONEY)


class ReportRepository:
    def __init__(self, db: Session, business_id: UUID) -> None:
        self.db, self.business_id = db, business_id

    def orders(self, start: datetime | None, end: datetime | None, status: str | None, customer_id: UUID | None, search: str, page: int, size: int) -> dict:
        filters = [Order.business_id == self.business_id, Order.deleted_at.is_(None)]
        if start: filters.append(Order.order_date >= start)
        if end: filters.append(Order.order_date < end)
        if status: filters.append(Order.status == status)
        if customer_id: filters.append(Order.customer_id == customer_id)
        if search:
            term = f"%{search}%"
            filters.append(or_(Order.order_number.ilike(term), Customer.display_name.ilike(term)))
        summary = self.db.execute(select(func.count(), func.count().filter(Order.status == "confirmed"), func.coalesce(func.sum(case((Order.status == "confirmed", Order.grand_total), else_=0)), 0)).join(Customer, and_(Customer.id == Order.customer_id, Customer.business_id == self.business_id)).where(*filters)).one()
        item_counts = select(OrderItem.order_id, func.count(OrderItem.id).label("item_count")).where(OrderItem.business_id == self.business_id, OrderItem.deleted_at.is_(None)).group_by(OrderItem.order_id).subquery()
        rows = self.db.execute(select(Order.id, Order.order_number, Order.customer_id, Customer.display_name, Order.status, Order.order_date, Order.subtotal, Order.tax_total, Order.grand_total, func.coalesce(item_counts.c.item_count, 0)).join(Customer, and_(Customer.id == Order.customer_id, Customer.business_id == self.business_id)).outerjoin(item_counts, item_counts.c.order_id == Order.id).where(*filters).order_by(Order.order_date.desc(), Order.id).offset((page - 1) * size).limit(size)).all()
        items = [{"order_id": r[0], "order_number": r[1], "customer_id": r[2], "customer_name": r[3], "status": r[4], "order_date": r[5], "subtotal": r[6], "tax_total": r[7], "grand_total": r[8], "item_count": r[9]} for r in rows]
        return {"items": items, "summary": {"matching_orders": summary[0], "confirmed_order_count": summary[1], "confirmed_order_value": money(summary[2])}, "total": summary[0], "page": page, "page_size": size}

    def payments(self, start: datetime | None, end: datetime | None, status: str | None, method: str | None, order_id: UUID | None, search: str, page: int, size: int) -> dict:
        filters = [Payment.business_id == self.business_id, Payment.deleted_at.is_(None), Order.business_id == self.business_id, Order.deleted_at.is_(None)]
        if start: filters.append(Payment.paid_at >= start)
        if end: filters.append(Payment.paid_at < end)
        if status: filters.append(Payment.status == status)
        if method: filters.append(Payment.payment_method == method)
        if order_id: filters.append(Payment.order_id == order_id)
        if search:
            term = f"%{search}%"
            filters.append(or_(Payment.payment_number.ilike(term), Order.order_number.ilike(term)))
        summary = self.db.execute(select(func.count(), func.count().filter(Payment.status == "completed"), func.count().filter(Payment.status == "pending"), func.count().filter(Payment.status == "failed"), func.count().filter(Payment.status == "cancelled"), func.coalesce(func.sum(case((Payment.status == "completed", Payment.amount), else_=0)), 0), func.coalesce(func.sum(case((Payment.status == "pending", Payment.amount), else_=0)), 0)).join(Order, and_(Order.id == Payment.order_id, Order.business_id == self.business_id)).where(*filters)).one()
        rows = self.db.execute(select(Payment.id, Payment.payment_number, Payment.order_id, Order.order_number, Payment.amount, Payment.payment_method, Payment.status, Payment.paid_at).join(Order, and_(Order.id == Payment.order_id, Order.business_id == self.business_id)).where(*filters).order_by(Payment.paid_at.desc(), Payment.id).offset((page - 1) * size).limit(size)).all()
        items = [{"payment_id": r[0], "payment_number": r[1], "order_id": r[2], "order_number": r[3], "amount": r[4], "payment_method": r[5], "status": r[6], "paid_at": r[7]} for r in rows]
        return {"items": items, "summary": {"matching_payments": summary[0], "completed_count": summary[1], "pending_count": summary[2], "failed_count": summary[3], "cancelled_count": summary[4], "completed_amount": money(summary[5]), "pending_amount": money(summary[6])}, "total": summary[0], "page": page, "page_size": size}

    def inventory(self, status: str | None, search: str, page: int, size: int) -> dict:
        join_condition = and_(Inventory.product_id == Product.id, Inventory.business_id == self.business_id, Inventory.deleted_at.is_(None))
        quantity = func.coalesce(Inventory.quantity_on_hand, 0)
        in_stock = and_(quantity > 0, or_(Product.reorder_level.is_(None), quantity > Product.reorder_level))
        low_stock = and_(quantity > 0, Product.reorder_level.is_not(None), quantity <= Product.reorder_level)
        out_of_stock = quantity == 0
        filters = [Product.business_id == self.business_id, Product.deleted_at.is_(None), Product.track_inventory.is_(True)]
        if search:
            term = f"%{search}%"
            filters.append(or_(Product.name.ilike(term), Product.sku.ilike(term)))
        if status: filters.append({"in_stock": in_stock, "low_stock": low_stock, "out_of_stock": out_of_stock}[status])
        summary = self.db.execute(select(func.count(), func.count().filter(in_stock), func.count().filter(low_stock), func.count().filter(out_of_stock)).select_from(Product).outerjoin(Inventory, join_condition).where(*filters)).one()
        rows = self.db.execute(select(Product.id, Product.name, Product.sku, quantity, Product.reorder_level, case((out_of_stock, "out_of_stock"), (low_stock, "low_stock"), else_="in_stock")).select_from(Product).outerjoin(Inventory, join_condition).where(*filters).order_by(Product.name.asc(), Product.id).offset((page - 1) * size).limit(size)).all()
        items = [{"product_id": r[0], "product_name": r[1], "sku": r[2], "quantity": r[3], "reorder_threshold": r[4], "stock_status": r[5]} for r in rows]
        return {"items": items, "summary": {"tracked_products": summary[0], "in_stock_count": summary[1], "low_stock_count": summary[2], "out_of_stock_count": summary[3]}, "total": summary[0], "page": page, "page_size": size}

    def customers(self, start: datetime | None, end: datetime | None, status: str | None, search: str, page: int, size: int) -> dict:
        order_totals = select(Order.customer_id, func.count(Order.id).label("order_count"), func.coalesce(func.sum(case((Order.status == "confirmed", Order.grand_total), else_=0)), 0).label("confirmed_value")).where(Order.business_id == self.business_id, Order.deleted_at.is_(None)).group_by(Order.customer_id).subquery()
        filters = [Customer.business_id == self.business_id, Customer.deleted_at.is_(None)]
        if start: filters.append(Customer.created_at >= start)
        if end: filters.append(Customer.created_at < end)
        if status: filters.append(Customer.status == status)
        if search:
            term = f"%{search}%"
            filters.append(or_(Customer.display_name.ilike(term), Customer.company_name.ilike(term), Customer.email.ilike(term), Customer.phone.ilike(term)))
        summary = self.db.execute(select(func.count(), func.count().filter(Customer.status == "active"), func.count().filter(Customer.status == "inactive"), func.coalesce(func.sum(func.coalesce(order_totals.c.confirmed_value, 0)), 0)).outerjoin(order_totals, order_totals.c.customer_id == Customer.id).where(*filters)).one()
        rows = self.db.execute(select(Customer.id, Customer.display_name, Customer.email, Customer.phone, Customer.status, Customer.created_at, func.coalesce(order_totals.c.order_count, 0), func.coalesce(order_totals.c.confirmed_value, 0)).outerjoin(order_totals, order_totals.c.customer_id == Customer.id).where(*filters).order_by(Customer.created_at.desc(), Customer.id).offset((page - 1) * size).limit(size)).all()
        items = [{"customer_id": r[0], "customer_name": r[1], "email": r[2], "phone": r[3], "status": r[4], "created_at": r[5], "order_count": r[6], "confirmed_order_value": money(r[7])} for r in rows]
        return {"items": items, "summary": {"matching_customers": summary[0], "active_count": summary[1], "inactive_count": summary[2], "confirmed_order_value": money(summary[3])}, "total": summary[0], "page": page, "page_size": size}
