from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models import Customer, Inventory, Invoice, Order, Payment, Product

ZERO = Decimal("0.00")
MONEY = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or ZERO)).quantize(MONEY)


class AnalyticsRepository:
    def __init__(self, db: Session, business_id: UUID) -> None:
        self.db, self.business_id = db, business_id

    def _count(self, model) -> int:
        return self.db.scalar(select(func.count()).select_from(model).where(model.business_id == self.business_id, model.deleted_at.is_(None))) or 0

    def summary(self) -> dict[str, int]:
        return {"total_customers": self._count(Customer), "total_products": self._count(Product), "total_orders": self._count(Order), "total_invoices": self._count(Invoice)}

    def customers(self) -> dict[str, int]:
        row = self.db.execute(select(func.count(), func.count().filter(Customer.status == "active"), func.count().filter(Customer.status == "inactive")).where(Customer.business_id == self.business_id, Customer.deleted_at.is_(None))).one()
        return {"total": row[0], "active": row[1], "inactive": row[2]}

    def orders(self, period_start: datetime) -> dict[str, int | Decimal]:
        counts = self.db.execute(select(func.count().filter(Order.status == "draft"), func.count().filter(Order.status == "confirmed"), func.count().filter(Order.status == "cancelled")).where(Order.business_id == self.business_id, Order.deleted_at.is_(None))).one()
        period = self.db.execute(select(func.count(), func.coalesce(func.sum(Order.grand_total), 0)).where(Order.business_id == self.business_id, Order.deleted_at.is_(None), Order.status == "confirmed", Order.order_date >= period_start)).one()
        period_value = money(period[1])
        average = money(period_value / period[0]) if period[0] else ZERO
        return {"draft_count": counts[0], "confirmed_count": counts[1], "cancelled_count": counts[2], "period_confirmed_count": period[0], "period_confirmed_order_value": period_value, "period_average_confirmed_order_value": average}

    def payments(self, period_start: datetime) -> dict[str, int | Decimal]:
        counts = self.db.execute(select(func.count().filter(Payment.status == "completed"), func.count().filter(Payment.status == "pending"), func.count().filter(Payment.status == "failed"), func.count().filter(Payment.status == "cancelled")).where(Payment.business_id == self.business_id, Payment.deleted_at.is_(None))).one()
        amounts = self.db.execute(select(func.coalesce(func.sum(case((Payment.status == "completed", Payment.amount), else_=0)), 0), func.coalesce(func.sum(case((Payment.status == "pending", Payment.amount), else_=0)), 0)).where(Payment.business_id == self.business_id, Payment.deleted_at.is_(None), Payment.paid_at >= period_start)).one()
        order_value = self.db.scalar(select(func.coalesce(func.sum(Order.grand_total), 0)).where(Order.business_id == self.business_id, Order.deleted_at.is_(None), Order.status == "confirmed")) or ZERO
        collected = self.db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.business_id == self.business_id, Payment.deleted_at.is_(None), Payment.status == "completed")) or ZERO
        return {"completed_count": counts[0], "pending_count": counts[1], "failed_count": counts[2], "cancelled_count": counts[3], "period_completed_amount": money(amounts[0]), "period_pending_amount": money(amounts[1]), "outstanding_amount": money(max(ZERO, order_value - collected))}

    def inventory(self) -> dict:
        join_condition = and_(Inventory.product_id == Product.id, Inventory.business_id == self.business_id, Inventory.deleted_at.is_(None))
        quantity = func.coalesce(Inventory.quantity_on_hand, 0)
        base = (Product.business_id == self.business_id, Product.deleted_at.is_(None), Product.track_inventory.is_(True))
        counts = self.db.execute(select(func.count(), func.count().filter(and_(quantity > 0, or_(Product.reorder_level.is_(None), quantity > Product.reorder_level))), func.count().filter(and_(quantity > 0, Product.reorder_level.is_not(None), quantity <= Product.reorder_level)), func.count().filter(quantity == 0)).select_from(Product).outerjoin(Inventory, join_condition).where(*base)).one()
        low_rows = self.db.execute(select(Product.id, Product.name, Product.sku, quantity, Product.reorder_level).select_from(Product).outerjoin(Inventory, join_condition).where(*base, or_(quantity == 0, and_(Product.reorder_level.is_not(None), quantity > 0, quantity <= Product.reorder_level))).order_by(quantity.asc(), Product.name.asc()).limit(5)).all()
        low = [{"product_id": row[0], "product_name": row[1], "sku": row[2], "quantity": row[3], "reorder_threshold": row[4], "stock_status": "out_of_stock" if row[3] == 0 else "low_stock"} for row in low_rows]
        return {"tracked_products": counts[0], "in_stock_count": counts[1], "low_stock_count": counts[2], "out_of_stock_count": counts[3], "low_stock_products": low}

    def recent(self, period_start: datetime, limit: int = 5) -> dict[str, list[dict]]:
        orders = self.db.execute(select(Order.id, Order.order_number, Order.status, Order.grand_total, Order.order_date).where(Order.business_id == self.business_id, Order.deleted_at.is_(None), Order.order_date >= period_start).order_by(Order.order_date.desc()).limit(limit)).all()
        payments = self.db.execute(select(Payment.id, Payment.payment_number, Payment.status, Payment.amount, Payment.paid_at).where(Payment.business_id == self.business_id, Payment.deleted_at.is_(None), Payment.paid_at >= period_start).order_by(Payment.paid_at.desc()).limit(limit)).all()
        invoices = self.db.execute(select(Invoice.id, Invoice.invoice_number, Invoice.status, Invoice.grand_total, Invoice.issued_at).where(Invoice.business_id == self.business_id, Invoice.deleted_at.is_(None), Invoice.issued_at >= period_start).order_by(Invoice.issued_at.desc()).limit(limit)).all()
        def records(rows): return [{"id": row[0], "reference": row[1], "status": row[2], "amount": row[3], "occurred_at": row[4]} for row in rows]
        return {"orders": records(orders), "payments": records(payments), "invoices": records(invoices)}
