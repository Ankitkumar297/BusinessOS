import csv
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from io import StringIO
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.services.report_service import ReportService

BATCH_SIZE = 100
CellKind = Literal["text", "decimal", "uuid", "timestamp", "enum", "integer"]


@dataclass(frozen=True)
class CsvColumn:
    heading: str
    field: str
    kind: CellKind


@dataclass(frozen=True)
class PreparedCsvExport:
    """A validated first page plus a lazy, single-use CSV chunk iterator."""

    chunks: Iterable[str]

    def __iter__(self) -> Iterator[str]:
        return iter(self.chunks)


ORDER_COLUMNS = (
    CsvColumn("Order ID", "order_id", "uuid"),
    CsvColumn("Order Number", "order_number", "text"),
    CsvColumn("Customer ID", "customer_id", "uuid"),
    CsvColumn("Customer Name", "customer_name", "text"),
    CsvColumn("Status", "status", "enum"),
    CsvColumn("Order Date", "order_date", "timestamp"),
    CsvColumn("Subtotal", "subtotal", "decimal"),
    CsvColumn("Tax Total", "tax_total", "decimal"),
    CsvColumn("Grand Total", "grand_total", "decimal"),
    CsvColumn("Item Count", "item_count", "integer"),
)
PAYMENT_COLUMNS = (
    CsvColumn("Payment ID", "payment_id", "uuid"),
    CsvColumn("Payment Number", "payment_number", "text"),
    CsvColumn("Order ID", "order_id", "uuid"),
    CsvColumn("Order Number", "order_number", "text"),
    CsvColumn("Amount", "amount", "decimal"),
    CsvColumn("Payment Method", "payment_method", "enum"),
    CsvColumn("Status", "status", "enum"),
    CsvColumn("Paid At", "paid_at", "timestamp"),
)
INVENTORY_COLUMNS = (
    CsvColumn("Product ID", "product_id", "uuid"),
    CsvColumn("Product Name", "product_name", "text"),
    CsvColumn("SKU", "sku", "text"),
    CsvColumn("Quantity", "quantity", "decimal"),
    CsvColumn("Reorder Threshold", "reorder_threshold", "decimal"),
    CsvColumn("Stock Status", "stock_status", "enum"),
)
CUSTOMER_COLUMNS = (
    CsvColumn("Customer ID", "customer_id", "uuid"),
    CsvColumn("Customer Name", "customer_name", "text"),
    CsvColumn("Email", "email", "text"),
    CsvColumn("Phone", "phone", "text"),
    CsvColumn("Status", "status", "enum"),
    CsvColumn("Created At", "created_at", "timestamp"),
    CsvColumn("Order Count", "order_count", "integer"),
    CsvColumn("Confirmed Order Value", "confirmed_order_value", "decimal"),
)


def neutralize_formula(value: str) -> str:
    candidate = value.lstrip()
    return f"'{value}" if candidate.startswith(("=", "+", "-", "@")) else value


def serialize_csv_value(value: object, kind: CellKind) -> str:
    if value is None:
        return ""
    if kind == "text":
        return neutralize_formula(str(value))
    if kind == "decimal":
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return format(value, "f")
    if kind == "uuid":
        return str(value)
    if kind == "timestamp":
        if not isinstance(value, datetime):
            raise TypeError("CSV timestamp values must be datetime instances.")
        if value.tzinfo is None:
            return value.isoformat()
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if kind == "enum":
        return str(value.value if isinstance(value, Enum) else value)
    if kind == "integer":
        return str(value)
    raise ValueError(f"Unsupported CSV cell kind: {kind}")


def csv_chunk(rows: Iterable[Sequence[str]]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerows(rows)
    return output.getvalue()


class ReportExportService:
    def __init__(
        self,
        db: Session | None = None,
        context: TenantContext | None = None,
        *,
        reports: ReportService | None = None,
    ) -> None:
        if reports is None:
            if db is None or context is None:
                raise ValueError("A database session and tenant context are required.")
            reports = ReportService(db, context)
        self.reports = reports

    def orders(self, start_date: date | None = None, end_date: date | None = None,
               status: str | None = None, customer_id: UUID | None = None,
               search: str = "") -> PreparedCsvExport:
        return self._prepare(
            lambda page, size: self.reports.orders(start_date, end_date, status, customer_id, search, page, size),
            ORDER_COLUMNS,
        )

    def payments(self, start_date: date | None = None, end_date: date | None = None,
                 status: str | None = None, payment_method: str | None = None,
                 order_id: UUID | None = None, search: str = "") -> PreparedCsvExport:
        return self._prepare(
            lambda page, size: self.reports.payments(start_date, end_date, status, payment_method, order_id, search, page, size),
            PAYMENT_COLUMNS,
        )

    def inventory(self, status: str | None = None, search: str = "") -> PreparedCsvExport:
        return self._prepare(
            lambda page, size: self.reports.inventory(status, search, page, size),
            INVENTORY_COLUMNS,
        )

    def customers(self, start_date: date | None = None, end_date: date | None = None,
                  status: str | None = None, search: str = "") -> PreparedCsvExport:
        return self._prepare(
            lambda page, size: self.reports.customers(start_date, end_date, status, search, page, size),
            CUSTOMER_COLUMNS,
        )

    def _prepare(self, fetch: Callable[[int, int], object], columns: Sequence[CsvColumn]) -> PreparedCsvExport:
        first_page = fetch(1, BATCH_SIZE)
        return PreparedCsvExport(self._chunks(fetch, first_page, columns))

    @staticmethod
    def _chunks(fetch: Callable[[int, int], object], first_page: object,
                columns: Sequence[CsvColumn]) -> Iterator[str]:
        yield csv_chunk([[column.heading for column in columns]])
        page_number = 1
        page_data = first_page
        exported = 0
        total = int(getattr(first_page, "total"))
        while exported < total:
            items = list(getattr(page_data, "items"))
            if not items:
                break
            remaining = total - exported
            selected = items[:remaining]
            yield csv_chunk(
                [
                    [serialize_csv_value(getattr(item, column.field), column.kind) for column in columns]
                    for item in selected
                ]
            )
            exported += len(selected)
            if exported >= total:
                break
            page_number += 1
            page_data = fetch(page_number, BATCH_SIZE)
