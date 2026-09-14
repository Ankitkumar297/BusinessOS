from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import re
from uuid import UUID, uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.models import Customer, Product, User
from app.services.invoice_document_service import (
    InvoiceDocumentData,
    InvoiceDocumentItem,
    InvoiceDocumentService,
    normalize_pdf_text,
    render_invoice_pdf,
    safe_filename,
)
from tests.test_invoices import confirmed, invoice
from tests.test_team import member, owner, team_client


def issued(client, headers, number="SO-DOCUMENT"):
    order, customer, product = confirmed(client, headers, number)
    response = invoice(client, headers, order["id"])
    assert response.status_code == 201, response.text
    return response.json(), customer, product


def context_for(client, business_id: str) -> TenantContext:
    with Session(client.test_engine) as db:
        user = db.query(User).filter(User.business_id == UUID(business_id)).first()
        assert user is not None
        return TenantContext(user_id=user.id, business_id=UUID(business_id), permissions=frozenset({"invoices.view"}))


def sample_document(items: int = 1) -> InvoiceDocumentData:
    item = InvoiceDocumentItem(
        product_name="A very long product name that wraps safely across table cells",
        product_sku="SKU-1", quantity=Decimal("2.000"), unit_price=Decimal("10.25"),
        tax_rate=Decimal("18.00"), line_subtotal=Decimal("20.50"),
        line_tax=Decimal("3.69"), line_total=Decimal("24.19"),
    )
    return InvoiceDocumentData(
        business_name="Alpha", invoice_number="INV-000001", status="issued",
        issued_at=datetime.now(UTC), order_number="SO-1", customer_name="Ava Patel",
        customer_email="ava@example.com", customer_address="1 Main Street\nPune",
        customer_tax_id="TAX-1", subtotal=Decimal("20.50"), tax_total=Decimal("3.69"),
        grand_total=Decimal("24.19"), items=tuple(item for _ in range(items)),
    )


def test_invoice_pdf_requires_authentication_and_view_permission(team_client):
    client = team_client
    assert client.get(f"/api/v1/invoices/{uuid4()}/pdf").status_code == 401
    headers, _ = owner(client)
    user = member(client, headers)
    login = client.post("/api/v1/auth/login", json={"email": user["email"], "password": "StrongPassword123!"}).json()
    denied = {"Authorization": "Bearer " + login["access_token"]}
    assert client.get(f"/api/v1/invoices/{uuid4()}/pdf", headers=denied).status_code == 403


def test_same_tenant_pdf_has_safe_headers_and_valid_content(team_client):
    client = team_client
    headers, _ = owner(client)
    made, _, _ = issued(client, headers)
    response = client.get(f"/api/v1/invoices/{made['id']}/pdf", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="invoice-INV-000001.pdf"'
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content.startswith(b"%PDF-") and len(response.content) > 1000


def test_document_data_uses_snapshots_decimals_and_no_live_commercial_queries(team_client, monkeypatch):
    client = team_client
    headers, account = owner(client)
    made, customer, product = issued(client, headers, "SO-SNAPSHOT")
    original_customer = made["customer_name"]
    original_product = made["items"][0]["product_name"]
    with Session(client.test_engine) as db:
        current_customer = db.get(Customer, UUID(customer["id"]))
        current_product = db.get(Product, UUID(product["id"]))
        assert current_customer is not None and current_product is not None
        current_customer.display_name = "Changed Customer"
        current_product.name = "Changed Product"
        db.commit()

    captured = []
    monkeypatch.setattr("app.services.invoice_document_service.render_invoice_pdf",
                        lambda document: captured.append(document) or b"%PDF-test")
    statements: list[str] = []
    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    event.listen(client.test_engine, "before_cursor_execute", capture_statement)
    try:
        response = client.get(f"/api/v1/invoices/{made['id']}/pdf", headers=headers)
    finally:
        event.remove(client.test_engine, "before_cursor_execute", capture_statement)
    assert response.status_code == 200 and len(captured) == 1
    document = captured[0]
    assert document.business_name == account["business"]["name"]
    assert document.invoice_number == made["invoice_number"]
    assert document.customer_name == original_customer and document.customer_name != "Changed Customer"
    assert document.items[0].product_name == original_product and document.items[0].product_name != "Changed Product"
    assert document.customer_email == made["customer_email"] and document.customer_address == made["customer_address"]
    assert document.items[0].product_sku == made["items"][0]["product_sku"]
    assert document.items[0].quantity == Decimal(made["items"][0]["quantity"])
    assert document.items[0].unit_price == Decimal(made["items"][0]["unit_price"])
    assert document.subtotal == Decimal(made["subtotal"])
    assert document.tax_total == Decimal(made["tax_total"])
    assert document.grand_total == Decimal(made["grand_total"])
    assert not any(re.search(r"\b(from|join)\s+customers\b", statement) for statement in statements)
    assert not any(re.search(r"\b(from|join)\s+products\b", statement) for statement in statements)
    assert not any(re.search(r"\b(from|join)\s+order_items\b", statement) for statement in statements)


def test_missing_and_cross_tenant_invoice_have_identical_not_found_response(team_client):
    client = team_client
    first, _ = owner(client)
    second, _ = owner(client, "Beta")
    made, _, _ = issued(client, first, "SO-PRIVATE")
    missing = client.get(f"/api/v1/invoices/{uuid4()}/pdf", headers=second)
    foreign = client.get(f"/api/v1/invoices/{made['id']}/pdf", headers=second)
    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json() == {"detail": "Invoice not found."}


def test_long_invoice_and_control_characters_render_without_clipping_or_crashing():
    document = replace(sample_document(180), customer_name="Ava\x00 Patel\x07", business_name="Alpha\x01")
    content = render_invoice_pdf(document)
    assert content.startswith(b"%PDF-")
    assert len(re.findall(br"/Type\s*/Page(?!s)", content)) > 1
    assert normalize_pdf_text("A\x00B\r\nC") == "AB\nC"


def test_filename_is_deterministic_and_blocks_header_or_path_injection():
    assert safe_filename("INV-000001") == "invoice-INV-000001.pdf"
    result = safe_filename('../INV\r\n"/../../evil')
    assert result == "invoice-INV-.-.-evil.pdf"
    assert "/" not in result and "\\" not in result and "\r" not in result and "\n" not in result and '"' not in result


def test_renderer_failure_is_controlled_and_existing_invoice_detail_still_works(team_client, monkeypatch):
    client = team_client
    headers, _ = owner(client)
    made, _, _ = issued(client, headers, "SO-FAILURE")
    monkeypatch.setattr("app.services.invoice_document_service.render_invoice_pdf",
                        lambda _document: (_ for _ in ()).throw(RuntimeError("internal renderer path")))
    failed = client.get(f"/api/v1/invoices/{made['id']}/pdf", headers=headers)
    assert failed.status_code == 500
    assert failed.json() == {"detail": "Unable to generate invoice document."}
    detail = client.get(f"/api/v1/invoices/{made['id']}", headers=headers)
    assert detail.status_code == 200 and detail.json()["invoice_number"] == made["invoice_number"]
