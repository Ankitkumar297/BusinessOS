import csv
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, call
from uuid import UUID

import pytest

from app.services.report_export_service import ReportExportService, neutralize_formula, serialize_csv_value

IDENTIFIER = UUID("12345678-1234-5678-1234-567812345678")


def page(items=(), total=None):
    values = list(items)
    return SimpleNamespace(items=values, total=len(values) if total is None else total)


def rows(export):
    return list(csv.reader(StringIO("".join(export))))


def order_row(number="SO-1", name="Ava"):
    return SimpleNamespace(order_id=IDENTIFIER, order_number=number, customer_id=IDENTIFIER,
                           customer_name=name, status="confirmed",
                           order_date=datetime(2026, 9, 11, 12, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))),
                           subtotal=Decimal("10.10"), tax_total=Decimal("1.82"),
                           grand_total=Decimal("11.92"), item_count=2)


def payment_row():
    return SimpleNamespace(payment_id=IDENTIFIER, payment_number="PAY-1", order_id=IDENTIFIER,
                           order_number="SO-1", amount=Decimal("5.10"), payment_method="bank_transfer",
                           status="completed", paid_at=datetime(2026, 9, 11, 12, 30, tzinfo=UTC))


def inventory_row():
    return SimpleNamespace(product_id=IDENTIFIER, product_name="Widget", sku="SKU-1",
                           quantity=Decimal("2.000"), reorder_threshold=Decimal("5.000"),
                           stock_status="low_stock")


def customer_row(name="Ava", email=None, phone=None):
    return SimpleNamespace(customer_id=IDENTIFIER, customer_name=name, email=email, phone=phone,
                           status="active", created_at=datetime(2026, 9, 11, 12, 30, tzinfo=UTC),
                           order_count=3, confirmed_order_value=Decimal("40.25"))


@pytest.mark.parametrize(("method", "service_method", "item", "expected"), [
    ("orders", "orders", order_row(), ["Order ID", "Order Number", "Customer ID", "Customer Name", "Status", "Order Date", "Subtotal", "Tax Total", "Grand Total", "Item Count"]),
    ("payments", "payments", payment_row(), ["Payment ID", "Payment Number", "Order ID", "Order Number", "Amount", "Payment Method", "Status", "Paid At"]),
    ("inventory", "inventory", inventory_row(), ["Product ID", "Product Name", "SKU", "Quantity", "Reorder Threshold", "Stock Status"]),
    ("customers", "customers", customer_row(), ["Customer ID", "Customer Name", "Email", "Phone", "Status", "Created At", "Order Count", "Confirmed Order Value"]),
])
def test_exact_headers_and_no_aggregate_summary_row(method, service_method, item, expected):
    reports = Mock()
    getattr(reports, service_method).return_value = page([item])
    exported = rows(getattr(ReportExportService(reports=reports), method)())
    assert exported[0] == expected
    assert len(exported) == 2


def test_empty_report_is_header_only():
    reports = Mock()
    reports.orders.return_value = page([])
    exported = rows(ReportExportService(reports=reports).orders())
    assert exported == [["Order ID", "Order Number", "Customer ID", "Customer Name", "Status", "Order Date", "Subtotal", "Tax Total", "Grand Total", "Item Count"]]


def test_batches_at_100_stops_at_service_total_and_fetches_first_page_eagerly():
    reports = Mock()
    first = [order_row(f"SO-{number}") for number in range(100)]
    reports.orders.side_effect = [page(first, 101), page([order_row("SO-100"), order_row("EXTRA")], 101)]
    export = ReportExportService(reports=reports).orders(search="batch")
    reports.orders.assert_called_once_with(None, None, None, None, "batch", 1, 100)
    exported = rows(export)
    assert len(exported) == 102
    assert exported[-1][1] == "SO-100"
    assert reports.orders.call_args_list == [call(None, None, None, None, "batch", 1, 100), call(None, None, None, None, "batch", 2, 100)]


def test_all_filters_pass_unchanged_to_existing_report_service():
    reports = Mock()
    reports.orders.return_value = reports.payments.return_value = reports.inventory.return_value = reports.customers.return_value = page([])
    start, end = date(2026, 9, 1), date(2026, 9, 11)
    service = ReportExportService(reports=reports)
    service.orders(start, end, "confirmed", IDENTIFIER, "order")
    service.payments(start, end, "completed", "cash", IDENTIFIER, "payment")
    service.inventory("low_stock", "widget")
    service.customers(start, end, "active", "ava")
    reports.orders.assert_called_once_with(start, end, "confirmed", IDENTIFIER, "order", 1, 100)
    reports.payments.assert_called_once_with(start, end, "completed", "cash", IDENTIFIER, "payment", 1, 100)
    reports.inventory.assert_called_once_with("low_stock", "widget", 1, 100)
    reports.customers.assert_called_once_with(start, end, "active", "ava", 1, 100)


def test_typed_values_preserve_decimal_uuid_enum_timestamp_and_nulls():
    class Status(Enum):
        COMPLETED = "completed"
    assert serialize_csv_value(Decimal("-10.50"), "decimal") == "-10.50"
    assert serialize_csv_value(Decimal("2.000"), "decimal") == "2.000"
    assert serialize_csv_value(IDENTIFIER, "uuid") == str(IDENTIFIER)
    assert serialize_csv_value(Status.COMPLETED, "enum") == "completed"
    value = datetime(2026, 9, 11, 18, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert serialize_csv_value(value, "timestamp") == "2026-09-11T12:30:00Z"
    assert serialize_csv_value(None, "text") == ""


def test_csv_writer_quotes_punctuation_newlines_and_preserves_unicode():
    reports = Mock()
    value = 'Northwind, "全球"\nOperations'
    reports.customers.return_value = page([customer_row(value, "āva@example.com", None)])
    raw = "".join(ReportExportService(reports=reports).customers())
    assert '"Northwind, ""全球""\nOperations"' in raw
    parsed = list(csv.reader(StringIO(raw)))
    assert parsed[1][1] == value
    assert parsed[1][2] == "āva@example.com"
    assert parsed[1][3] == ""


@pytest.mark.parametrize("value", ["=SUM(A1:A2)", "+cmd", "-danger", "@command", "  =hidden"])
def test_formula_like_text_is_neutralized(value):
    assert neutralize_formula(value) == "'" + value


def test_safe_text_and_negative_decimal_are_not_changed():
    assert neutralize_formula("Order - 10") == "Order - 10"
    assert serialize_csv_value(Decimal("-10.50"), "decimal") == "-10.50"
