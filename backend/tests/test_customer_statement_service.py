from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.models import Business, Customer, Invoice, Order, Payment
from app.services.customer_statement_service import CustomerStatementService


def business(db, name: str = "Alpha") -> Business:
    item = Business(name=name, slug=f"{name.lower()}-{uuid4().hex[:8]}", is_active=True)
    db.add(item)
    db.flush()
    return item


def customer(db, owner: Business, name: str = "Ava Patel", *, deleted_at=None) -> Customer:
    item = Customer(
        business_id=owner.id,
        customer_type="business",
        display_name=name,
        company_name=f"{name} Ltd",
        email=f"{name.replace(' ', '.').lower()}@example.com",
        status="active",
        deleted_at=deleted_at,
    )
    db.add(item)
    db.flush()
    return item


def order(
    db,
    owner: Business,
    buyer: Customer,
    number: str,
    amount: str,
    when: datetime,
    *,
    status: str = "confirmed",
    item_id: UUID | None = None,
    deleted_at=None,
) -> Order:
    item = Order(
        id=item_id or uuid4(),
        business_id=owner.id,
        customer_id=buyer.id,
        order_number=number,
        status=status,
        order_date=when,
        subtotal=Decimal(amount),
        tax_total=Decimal("0.00"),
        grand_total=Decimal(amount),
        deleted_at=deleted_at,
    )
    db.add(item)
    db.flush()
    return item


def payment(
    db,
    owner: Business,
    source: Order,
    number: str,
    amount: str,
    when: datetime,
    *,
    status: str = "completed",
    item_id: UUID | None = None,
    deleted_at=None,
) -> Payment:
    item = Payment(
        id=item_id or uuid4(),
        business_id=owner.id,
        order_id=source.id,
        payment_number=number,
        amount=Decimal(amount),
        payment_method="cash",
        status=status,
        paid_at=when,
        deleted_at=deleted_at,
    )
    db.add(item)
    db.flush()
    return item


def invoice(db, owner: Business, source: Order, *, deleted_at=None) -> Invoice:
    item = Invoice(
        business_id=owner.id,
        order_id=source.id,
        invoice_number=f"INV-{source.order_number}",
        status="issued",
        issued_at=source.order_date,
        order_number=source.order_number,
        customer_name=source.customer.display_name,
        customer_email=source.customer.email,
        customer_address=None,
        customer_tax_id=None,
        subtotal=source.subtotal,
        tax_total=source.tax_total,
        grand_total=source.grand_total,
        deleted_at=deleted_at,
    )
    db.add(item)
    db.flush()
    return item


def service(db, owner: Business) -> CustomerStatementService:
    return CustomerStatementService(
        db,
        TenantContext(user_id=uuid4(), business_id=owner.id, permissions=frozenset({"reports.view"})),
    )


def test_statement_uses_confirmed_orders_completed_payments_and_pending_summary(db):
    owner = business(db)
    buyer = customer(db, owner)
    first = order(db, owner, buyer, "SO-1", "10.15", datetime(2026, 1, 1, tzinfo=UTC))
    order(db, owner, buyer, "SO-DRAFT", "99.00", datetime(2026, 1, 2, tzinfo=UTC), status="draft")
    order(db, owner, buyer, "SO-CANCELLED", "99.00", datetime(2026, 1, 2, tzinfo=UTC), status="cancelled")
    payment(db, owner, first, "PAY-1", "4.05", datetime(2026, 1, 3, tzinfo=UTC))
    payment(db, owner, first, "PAY-PENDING", "2.50", datetime(2026, 1, 4, tzinfo=UTC), status="pending")
    payment(db, owner, first, "PAY-FAILED", "3.00", datetime(2026, 1, 4, tzinfo=UTC), status="failed")
    payment(db, owner, first, "PAY-CANCELLED", "3.00", datetime(2026, 1, 4, tzinfo=UTC), status="cancelled")

    result = service(db, owner).statement(buyer.id)

    assert [entry.type for entry in result.entries] == ["order_charge", "payment"]
    assert result.statement.opening_balance == Decimal("0.00")
    assert result.statement.period_debits == Decimal("10.15")
    assert result.statement.period_credits == Decimal("4.05")
    assert result.statement.pending_payment_total == Decimal("2.50")
    assert result.statement.closing_balance == Decimal("6.10")
    assert [entry.running_balance for entry in result.entries] == [Decimal("10.15"), Decimal("6.10")]
    assert result.entries[0].invoice_id is None and result.entries[0].invoice_number is None


def test_statement_date_boundaries_opening_and_optional_ranges(db):
    owner = business(db)
    buyer = customer(db, owner)
    before = order(db, owner, buyer, "SO-BEFORE", "100.00", datetime(2026, 1, 1, 10, tzinfo=UTC))
    payment(db, owner, before, "PAY-BEFORE", "20.00", datetime(2026, 1, 2, tzinfo=UTC))
    inside = order(db, owner, buyer, "SO-START", "50.00", datetime(2026, 1, 10, tzinfo=UTC))
    payment(db, owner, inside, "PAY-END", "10.00", datetime(2026, 1, 20, 23, 59, tzinfo=UTC))
    order(db, owner, buyer, "SO-AFTER", "30.00", datetime(2026, 1, 21, tzinfo=UTC))
    payment(db, owner, inside, "PAY-PENDING", "7.00", datetime(2026, 1, 20, tzinfo=UTC), status="pending")

    bounded = service(db, owner).statement(buyer.id, date(2026, 1, 10), date(2026, 1, 20))
    assert bounded.statement.opening_balance == Decimal("80.00")
    assert [entry.order_number for entry in bounded.entries] == ["SO-START", "SO-START"]
    assert bounded.statement.period_debits == Decimal("50.00")
    assert bounded.statement.period_credits == Decimal("10.00")
    assert bounded.statement.closing_balance == Decimal("120.00")
    assert bounded.statement.pending_payment_total == Decimal("7.00")

    start_only = service(db, owner).statement(buyer.id, start_date=date(2026, 1, 10))
    assert start_only.statement.opening_balance == Decimal("80.00")
    assert start_only.total == 3 and start_only.statement.closing_balance == Decimal("150.00")
    end_only = service(db, owner).statement(buyer.id, end_date=date(2026, 1, 20))
    assert end_only.statement.opening_balance == Decimal("0.00")
    assert end_only.total == 4 and end_only.statement.closing_balance == Decimal("120.00")


def test_statement_ordering_is_deterministic_and_running_balance_spans_pages(db):
    owner = business(db)
    buyer = customer(db, owner)
    same_time = datetime(2026, 2, 1, 12, tzinfo=UTC)
    later_id = UUID(int=2)
    earlier_id = UUID(int=1)
    second = order(db, owner, buyer, "SO-2", "5.00", same_time, item_id=later_id)
    order(db, owner, buyer, "SO-1", "7.00", same_time, item_id=earlier_id)
    payment(db, owner, second, "PAY-1", "20.00", same_time, item_id=UUID(int=3))

    first_run = service(db, owner).statement(buyer.id, page=1, page_size=2)
    second_page = service(db, owner).statement(buyer.id, page=2, page_size=2)
    repeated = service(db, owner).statement(buyer.id, page=1, page_size=2)

    assert [entry.order_number for entry in first_run.entries] == ["SO-1", "SO-2"]
    assert [entry.order_number for entry in repeated.entries] == ["SO-1", "SO-2"]
    assert first_run.total == second_page.total == 3
    assert first_run.statement.period_debits == second_page.statement.period_debits == Decimal("12.00")
    assert first_run.statement.period_credits == second_page.statement.period_credits == Decimal("20.00")
    assert second_page.entries[0].type == "payment"
    assert second_page.entries[0].running_balance == Decimal("-8.00")
    assert second_page.statement.closing_balance == Decimal("-8.00")


def test_invoice_metadata_is_optional_and_deleted_invoice_does_not_remove_debit(db):
    owner = business(db)
    buyer = customer(db, owner)
    source = order(db, owner, buyer, "SO-INVOICE", "25.00", datetime(2026, 3, 1, tzinfo=UTC))
    paid = payment(db, owner, source, "PAY-INVOICE", "5.00", datetime(2026, 3, 2, tzinfo=UTC))
    document = invoice(db, owner, source)

    present = service(db, owner).statement(buyer.id)
    assert all(entry.invoice_id == document.id for entry in present.entries)
    assert all(entry.invoice_number == document.invoice_number for entry in present.entries)
    assert present.entries[1].payment_id == paid.id

    document.deleted_at = datetime(2026, 3, 3, tzinfo=UTC)
    db.flush()
    absent = service(db, owner).statement(buyer.id)
    assert absent.total == 2
    assert absent.statement.period_debits == Decimal("25.00")
    assert all(entry.invoice_id is None and entry.invoice_number is None for entry in absent.entries)


def test_deleted_sources_and_other_tenants_never_affect_statement(db):
    owner = business(db)
    buyer = customer(db, owner)
    kept = order(db, owner, buyer, "SO-KEPT", "12.00", datetime(2026, 4, 1, tzinfo=UTC))
    order(db, owner, buyer, "SO-DELETED", "100.00", datetime(2026, 4, 1, tzinfo=UTC), deleted_at=datetime.now(UTC))
    payment(db, owner, kept, "PAY-DELETED", "10.00", datetime(2026, 4, 2, tzinfo=UTC), deleted_at=datetime.now(UTC))

    foreign_owner = business(db, "Beta")
    foreign_buyer = customer(db, foreign_owner, "Foreign Buyer")
    foreign_order = order(db, foreign_owner, foreign_buyer, "SO-FOREIGN", "500.00", datetime(2026, 4, 1, tzinfo=UTC))
    payment(db, foreign_owner, foreign_order, "PAY-FOREIGN", "100.00", datetime(2026, 4, 2, tzinfo=UTC))

    result = service(db, owner).statement(buyer.id)
    assert result.total == 1
    assert result.statement.period_debits == Decimal("12.00")
    assert result.statement.period_credits == Decimal("0.00")
    with pytest.raises(AppError, match="Customer not found") as foreign:
        service(db, owner).statement(foreign_buyer.id)
    assert foreign.value.status_code == 404


def test_empty_deleted_customer_and_invalid_range(db):
    owner = business(db)
    empty = customer(db, owner, "Empty Buyer")
    result = service(db, owner).statement(empty.id)
    assert result.entries == [] and result.total == 0
    assert result.statement.opening_balance == result.statement.closing_balance == Decimal("0.00")

    deleted = customer(db, owner, "Deleted Buyer", deleted_at=datetime.now(UTC))
    with pytest.raises(AppError, match="Customer not found") as missing:
        service(db, owner).statement(deleted.id)
    assert missing.value.status_code == 404
    with pytest.raises(AppError, match="start_date must be on or before end_date") as invalid:
        service(db, owner).statement(empty.id, date(2026, 5, 2), date(2026, 5, 1))
    assert invalid.value.status_code == 422
