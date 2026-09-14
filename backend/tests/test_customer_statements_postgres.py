import os
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.test_customers import create as create_customer
from tests.test_invoices import confirmed, invoice
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def url(customer_id: str, query: str = "") -> str:
    return f"/api/v1/reports/customers/{customer_id}/statement{query}"


def test_postgres_statement_never_leaks_cross_tenant_financial_data(team_client):
    client = team_client
    own_headers, _ = owner(client)
    foreign_headers, _ = owner(client, "Beta")
    own_order, own_customer, _ = confirmed(client, own_headers, "SO-SHARED")
    foreign_order, foreign_customer, _ = confirmed(client, foreign_headers, "SO-SHARED")

    assert invoice(client, foreign_headers, foreign_order["id"]).status_code == 201
    assert client.post(
        "/api/v1/payments",
        headers=foreign_headers,
        json={
            "order_id": foreign_order["id"],
            "payment_number": "PAY-SHARED",
            "amount": "7.77",
            "payment_method": "cash",
        },
    ).status_code == 201

    response = client.get(url(own_customer["id"]), headers=own_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["entries"][0]["order_id"] == own_order["id"]
    assert body["entries"][0]["invoice_id"] is None
    assert body["statement"]["period_debits"] == "20.00"
    assert body["statement"]["period_credits"] == "0.00"
    assert body["statement"]["pending_payment_total"] == "0.00"

    foreign = client.get(url(foreign_customer["id"]), headers=own_headers)
    missing = client.get(url("00000000-0000-0000-0000-000000000099"), headers=own_headers)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Customer not found."}


def test_postgres_union_window_numeric_ordering_and_pagination(team_client):
    client = team_client
    headers, registered = owner(client)
    buyer = create_customer(client, headers, "Window Buyer")
    business_id = UUID(registered["business"]["id"])
    customer_id = UUID(buyer["id"])
    before_order = UUID(int=10)
    before_payment = UUID(int=11)
    first_order = UUID(int=1)
    second_order = UUID(int=2)
    completed_payment = UUID(int=3)
    pending_payment = UUID(int=4)
    before_time = datetime(2026, 1, 1, 10, tzinfo=UTC)
    same_time = datetime(2026, 2, 1, 12, tzinfo=UTC)

    with client.test_engine.begin() as connection:
        for item_id, number, amount, when in (
            (before_order, "SO-BEFORE", "1.11", before_time),
            (first_order, "SO-FIRST", "0.10", same_time),
            (second_order, "SO-SECOND", "0.20", same_time),
        ):
            connection.execute(
                text(
                    "INSERT INTO orders "
                    "(id, business_id, customer_id, order_number, status, order_date, subtotal, tax_total, grand_total) "
                    "VALUES (:id, :business, :customer, :number, 'confirmed', :when, :amount, 0, :amount)"
                ),
                {
                    "id": item_id,
                    "business": business_id,
                    "customer": customer_id,
                    "number": number,
                    "when": when,
                    "amount": amount,
                },
            )
        for item_id, order_id, number, amount, status, when in (
            (before_payment, before_order, "PAY-BEFORE", "0.11", "completed", before_time),
            (completed_payment, first_order, "PAY-COMPLETE", "0.05", "completed", same_time),
            (pending_payment, first_order, "PAY-PENDING", "0.07", "pending", same_time),
        ):
            connection.execute(
                text(
                    "INSERT INTO payments "
                    "(id, business_id, order_id, payment_number, amount, payment_method, status, paid_at) "
                    "VALUES (:id, :business, :order, :number, :amount, 'cash', :status, :when)"
                ),
                {
                    "id": item_id,
                    "business": business_id,
                    "order": order_id,
                    "number": number,
                    "amount": amount,
                    "status": status,
                    "when": when,
                },
            )

    query = "?start_date=2026-02-01&page=1&page_size=1"
    first = client.get(url(buyer["id"], query), headers=headers)
    second = client.get(url(buyer["id"], query.replace("page=1", "page=2")), headers=headers)
    third = client.get(url(buyer["id"], query.replace("page=1", "page=3")), headers=headers)
    repeated = client.get(url(buyer["id"], query), headers=headers)
    assert first.status_code == second.status_code == third.status_code == repeated.status_code == 200

    first_body, second_body, third_body = first.json(), second.json(), third.json()
    assert first_body["entries"][0]["order_id"] == str(first_order)
    assert second_body["entries"][0]["order_id"] == str(second_order)
    assert third_body["entries"][0]["type"] == "payment"
    assert first_body["entries"][0]["running_balance"] == "1.10"
    assert second_body["entries"][0]["running_balance"] == "1.30"
    assert third_body["entries"][0]["running_balance"] == "1.25"
    assert repeated.json()["entries"] == first_body["entries"]

    expected_summary = {
        "start_date": "2026-02-01",
        "end_date": None,
        "opening_balance": "1.00",
        "period_debits": "0.30",
        "period_credits": "0.05",
        "closing_balance": "1.25",
        "pending_payment_total": "0.07",
    }
    assert first_body["statement"] == second_body["statement"] == third_body["statement"] == expected_summary
    assert first_body["total"] == second_body["total"] == third_body["total"] == 3


def test_postgres_deleted_sources_invoice_metadata_and_read_only_behavior(team_client):
    client = team_client
    headers, _ = owner(client)
    source, buyer, _ = confirmed(client, headers, "SO-DELETION")
    created_invoice = invoice(client, headers, source["id"])
    assert created_invoice.status_code == 201
    created_payment = client.post(
        "/api/v1/payments",
        headers=headers,
        json={
            "order_id": source["id"],
            "payment_number": "PAY-DELETION",
            "amount": "3.33",
            "payment_method": "cash",
        },
    )
    assert created_payment.status_code == 201

    with client.test_engine.connect() as connection:
        counts_before = connection.execute(
            text("SELECT (SELECT count(*) FROM orders), (SELECT count(*) FROM payments), (SELECT count(*) FROM invoices)")
        ).one()
    initial = client.get(url(buyer["id"]), headers=headers).json()
    assert initial["total"] == 2
    assert all(entry["invoice_id"] == created_invoice.json()["id"] for entry in initial["entries"])
    with client.test_engine.connect() as connection:
        counts_after = connection.execute(
            text("SELECT (SELECT count(*) FROM orders), (SELECT count(*) FROM payments), (SELECT count(*) FROM invoices)")
        ).one()
    assert counts_after == counts_before

    with client.test_engine.begin() as connection:
        connection.execute(
            text("UPDATE invoices SET deleted_at = now() WHERE id = :id"),
            {"id": UUID(created_invoice.json()["id"])},
        )
    without_invoice = client.get(url(buyer["id"]), headers=headers).json()
    assert without_invoice["statement"]["period_debits"] == "20.00"
    assert all(entry["invoice_id"] is None and entry["invoice_number"] is None for entry in without_invoice["entries"])

    with client.test_engine.begin() as connection:
        connection.execute(
            text("UPDATE payments SET deleted_at = now() WHERE id = :id"),
            {"id": UUID(created_payment.json()["id"])},
        )
    without_payment = client.get(url(buyer["id"]), headers=headers).json()
    assert without_payment["total"] == 1
    assert without_payment["statement"]["period_credits"] == "0.00"

    with client.test_engine.begin() as connection:
        connection.execute(
            text("UPDATE orders SET deleted_at = now() WHERE id = :id"),
            {"id": UUID(source["id"])},
        )
    without_order = client.get(url(buyer["id"]), headers=headers).json()
    assert without_order["total"] == 0
    assert without_order["statement"]["period_debits"] == "0.00"
