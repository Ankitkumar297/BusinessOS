from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Numeric, Uuid, and_, cast, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.models import Customer, Invoice, Order, Payment

MONEY_TYPE = Numeric(14, 2)
ZERO = Decimal("0.00")


class CustomerStatementRepository:
    def __init__(self, db: Session, business_id: UUID) -> None:
        self.db = db
        self.business_id = business_id

    def customer(self, customer_id: UUID) -> Customer | None:
        return self.db.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.business_id == self.business_id,
                Customer.deleted_at.is_(None),
            )
        )

    def _invoice_join(self):
        return and_(
            Invoice.business_id == self.business_id,
            Invoice.order_id == Order.id,
            Invoice.deleted_at.is_(None),
        )

    def _ledger(self, customer_id: UUID):
        no_uuid = cast(literal(None), Uuid())
        no_text = cast(literal(None), Payment.payment_number.type)
        zero = cast(literal(ZERO), MONEY_TYPE)

        charges = (
            select(
                literal("order_charge").label("entry_type"),
                literal(0).label("type_rank"),
                Order.order_date.label("effective_at"),
                Order.id.label("source_id"),
                Order.id.label("order_id"),
                Order.order_number.label("order_number"),
                Invoice.id.label("invoice_id"),
                Invoice.invoice_number.label("invoice_number"),
                no_uuid.label("payment_id"),
                no_text.label("payment_number"),
                no_text.label("payment_method"),
                Order.grand_total.label("debit"),
                zero.label("credit"),
            )
            .select_from(Order)
            .outerjoin(Invoice, self._invoice_join())
            .where(
                Order.business_id == self.business_id,
                Order.customer_id == customer_id,
                Order.status == "confirmed",
                Order.deleted_at.is_(None),
            )
        )
        credits = (
            select(
                literal("payment").label("entry_type"),
                literal(1).label("type_rank"),
                Payment.paid_at.label("effective_at"),
                Payment.id.label("source_id"),
                Order.id.label("order_id"),
                Order.order_number.label("order_number"),
                Invoice.id.label("invoice_id"),
                Invoice.invoice_number.label("invoice_number"),
                Payment.id.label("payment_id"),
                Payment.payment_number.label("payment_number"),
                Payment.payment_method.label("payment_method"),
                zero.label("debit"),
                Payment.amount.label("credit"),
            )
            .select_from(Payment)
            .join(
                Order,
                and_(
                    Order.id == Payment.order_id,
                    Order.business_id == self.business_id,
                    Order.customer_id == customer_id,
                    Order.deleted_at.is_(None),
                ),
            )
            .outerjoin(Invoice, self._invoice_join())
            .where(
                Payment.business_id == self.business_id,
                Payment.status == "completed",
                Payment.deleted_at.is_(None),
            )
        )
        return union_all(charges, credits).subquery("customer_statement_ledger")

    @staticmethod
    def _period(ledger, start: datetime | None, end: datetime | None):
        query = select(ledger)
        if start is not None:
            query = query.where(ledger.c.effective_at >= start)
        if end is not None:
            query = query.where(ledger.c.effective_at < end)
        return query.subquery("customer_statement_period")

    def opening_balance(self, customer_id: UUID, start: datetime | None) -> Decimal:
        if start is None:
            return ZERO
        ledger = self._ledger(customer_id)
        value = self.db.scalar(
            select(func.coalesce(func.sum(ledger.c.debit - ledger.c.credit), ZERO)).where(
                ledger.c.effective_at < start
            )
        )
        return Decimal(str(value or ZERO))

    def pending_total(
        self, customer_id: UUID, start: datetime | None, end: datetime | None
    ) -> Decimal:
        query = (
            select(func.coalesce(func.sum(Payment.amount), ZERO))
            .select_from(Payment)
            .join(
                Order,
                and_(
                    Order.id == Payment.order_id,
                    Order.business_id == self.business_id,
                    Order.customer_id == customer_id,
                    Order.deleted_at.is_(None),
                ),
            )
            .where(
                Payment.business_id == self.business_id,
                Payment.status == "pending",
                Payment.deleted_at.is_(None),
            )
        )
        if start is not None:
            query = query.where(Payment.paid_at >= start)
        if end is not None:
            query = query.where(Payment.paid_at < end)
        return Decimal(str(self.db.scalar(query) or ZERO))

    def entries(
        self,
        customer_id: UUID,
        start: datetime | None,
        end: datetime | None,
        opening: Decimal,
        page: int,
        size: int,
    ) -> dict[str, object]:
        period = self._period(self._ledger(customer_id), start, end)
        ordering = (period.c.effective_at, period.c.type_rank, period.c.source_id)
        running = (
            cast(literal(opening), MONEY_TYPE)
            + func.sum(period.c.debit - period.c.credit).over(order_by=ordering, rows=(None, 0))
        ).label("running_balance")
        ranked = select(period, running).subquery("customer_statement_ranked")

        summary = self.db.execute(
            select(
                func.count(period.c.source_id),
                func.coalesce(func.sum(period.c.debit), ZERO),
                func.coalesce(func.sum(period.c.credit), ZERO),
            )
        ).one()
        rows = self.db.execute(
            select(ranked)
            .order_by(ranked.c.effective_at, ranked.c.type_rank, ranked.c.source_id)
            .offset((page - 1) * size)
            .limit(size)
        ).mappings().all()
        return {
            "rows": rows,
            "total": int(summary[0]),
            "period_debits": Decimal(str(summary[1] or ZERO)),
            "period_credits": Decimal(str(summary[2] or ZERO)),
        }
