"""Read-only, tenant-scoped rendering of immutable invoice snapshots."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import escape
from io import BytesIO
import logging
import re
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.models import Business
from app.repositories.invoices import InvoiceRepository

logger = logging.getLogger("businessos.invoice.documents")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class InvoiceDocumentItem:
    product_name: str
    product_sku: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class InvoiceDocumentData:
    business_name: str
    invoice_number: str
    status: str
    issued_at: datetime
    order_number: str
    customer_name: str
    customer_email: str | None
    customer_address: str | None
    customer_tax_id: str | None
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    items: tuple[InvoiceDocumentItem, ...]


@dataclass(frozen=True)
class GeneratedInvoiceDocument:
    content: bytes
    filename: str


def normalize_pdf_text(value: str) -> str:
    """Remove unsafe controls without mutating stored values."""
    return _CONTROL_CHARACTERS.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))


def safe_filename(invoice_number: str) -> str:
    candidate = _UNSAFE_FILENAME.sub("-", normalize_pdf_text(invoice_number))
    candidate = re.sub(r"\.{2,}", ".", candidate).strip("._-")[:64]
    return f"invoice-{candidate or 'document'}.pdf"


def _paragraph_text(value: str) -> str:
    # Built-in ReportLab fonts have a deliberately limited WinAnsi contract.
    limited = normalize_pdf_text(value).encode("cp1252", errors="replace").decode("cp1252")
    return escape(limited).replace("\n", "<br/>")


def _decimal(value: Decimal, places: int | None = None) -> str:
    return format(value, f".{places}f") if places is not None else format(value, "f")


def render_invoice_pdf(document: InvoiceDocumentData) -> bytes:
    output = BytesIO()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("InvoiceBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10)
    right = ParagraphStyle("InvoiceRight", parent=body, alignment=TA_RIGHT)
    pdf = SimpleDocTemplate(output, pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"Invoice {normalize_pdf_text(document.invoice_number)}")
    story = [
        Paragraph(_paragraph_text(document.business_name), styles["Heading2"]),
        Paragraph("INVOICE", styles["Title"]),
        Spacer(1, 4 * mm),
        Table([
            ["Invoice Number", Paragraph(_paragraph_text(document.invoice_number), body), "Issue Date", document.issued_at.date().isoformat()],
            ["Status", Paragraph(_paragraph_text(document.status.upper()), body), "Order Number", Paragraph(_paragraph_text(document.order_number), body)],
        ], colWidths=[28 * mm, 57 * mm, 25 * mm, 70 * mm], style=TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#6B7280")),
            ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#6B7280")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])),
        Spacer(1, 5 * mm),
        Paragraph("Bill To", styles["Heading3"]),
        Paragraph(_paragraph_text(document.customer_name), body),
    ]
    for value in (document.customer_email, document.customer_address,
                  f"Tax ID: {document.customer_tax_id}" if document.customer_tax_id else None):
        if value:
            story.append(Paragraph(_paragraph_text(value), body))
    story.append(Spacer(1, 5 * mm))

    rows = [[Paragraph(value, body) for value in ("Product", "SKU", "Quantity", "Unit Price", "Tax Rate", "Subtotal", "Tax", "Total")]]
    for item in document.items:
        rows.append([
            Paragraph(_paragraph_text(item.product_name), body),
            Paragraph(_paragraph_text(item.product_sku), body),
            Paragraph(_decimal(item.quantity), right),
            Paragraph(_decimal(item.unit_price, 2), right),
            Paragraph(f"{_decimal(item.tax_rate)}%", right),
            Paragraph(_decimal(item.line_subtotal, 2), right),
            Paragraph(_decimal(item.line_tax, 2), right),
            Paragraph(_decimal(item.line_total, 2), right),
        ])
    item_table = Table(rows, repeatRows=1, splitByRow=1,
                       colWidths=[46 * mm, 23 * mm, 18 * mm, 22 * mm, 18 * mm, 23 * mm, 18 * mm, 22 * mm])
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([item_table, Spacer(1, 5 * mm)])
    totals = Table([
        ["Subtotal", _decimal(document.subtotal, 2)],
        ["Tax Total", _decimal(document.tax_total, 2)],
        ["Grand Total", _decimal(document.grand_total, 2)],
    ], colWidths=[35 * mm, 35 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.HexColor("#111827")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("TOPPADDING", (0, -1), (-1, -1), 6),
    ]))
    story.append(totals)
    pdf.build(story)
    return output.getvalue()


class InvoiceDocumentService:
    def __init__(self, db: Session, context: TenantContext) -> None:
        self.db = db
        self.context = context

    def prepare(self, invoice_id: UUID) -> InvoiceDocumentData:
        invoice = InvoiceRepository(self.db, self.context.business_id).invoice(invoice_id)
        if not invoice:
            raise AppError(404, "Invoice not found.")
        business_name = self.db.scalar(select(Business.name).where(
            Business.id == self.context.business_id, Business.deleted_at.is_(None)))
        if not business_name:
            raise AppError(404, "Invoice not found.")
        return InvoiceDocumentData(
            business_name=normalize_pdf_text(business_name),
            invoice_number=normalize_pdf_text(invoice.invoice_number), status=invoice.status,
            issued_at=invoice.issued_at, order_number=normalize_pdf_text(invoice.order_number),
            customer_name=normalize_pdf_text(invoice.customer_name),
            customer_email=normalize_pdf_text(invoice.customer_email) if invoice.customer_email else None,
            customer_address=normalize_pdf_text(invoice.customer_address) if invoice.customer_address else None,
            customer_tax_id=normalize_pdf_text(invoice.customer_tax_id) if invoice.customer_tax_id else None,
            subtotal=invoice.subtotal, tax_total=invoice.tax_total, grand_total=invoice.grand_total,
            items=tuple(InvoiceDocumentItem(
                product_name=normalize_pdf_text(item.product_name), product_sku=normalize_pdf_text(item.product_sku),
                quantity=item.quantity, unit_price=item.unit_price, tax_rate=item.tax_rate,
                line_subtotal=item.line_subtotal, line_tax=item.line_tax, line_total=item.line_total,
            ) for item in invoice.items if item.deleted_at is None),
        )

    def generate(self, invoice_id: UUID) -> GeneratedInvoiceDocument:
        document = self.prepare(invoice_id)
        try:
            content = render_invoice_pdf(document)
        except Exception as exc:
            logger.exception("Invoice PDF rendering failed invoice_id=%s business_id=%s",
                             invoice_id, self.context.business_id)
            raise AppError(500, "Unable to generate invoice document.") from exc
        return GeneratedInvoiceDocument(content=content, filename=safe_filename(document.invoice_number))
