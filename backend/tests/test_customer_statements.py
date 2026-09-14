from datetime import date, timedelta
from uuid import uuid4

from tests.test_customers import create as create_customer
from tests.test_invoices import confirmed, invoice
from tests.test_team import member, owner, team_client


def statement_url(customer_id: str, query: str = "") -> str:
    return f"/api/v1/reports/customers/{customer_id}/statement{query}"


def login(client, user: dict) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": "StrongPassword123!"},
    )
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_statement_api_requires_authentication_and_reports_permission(team_client):
    client = team_client
    headers, _ = owner(client)
    buyer = create_customer(client, headers)
    url = statement_url(buyer["id"])

    assert client.get(url).status_code == 401
    no_roles = member(client, headers)
    assert client.get(url, headers=login(client, no_roles)).status_code == 403

    role = client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": "Customer reader", "permission_codes": ["customers.view"]},
    ).json()
    customer_reader = member(client, headers, [role["id"]])
    assert client.get(url, headers=login(client, customer_reader)).status_code == 403
    assert client.get(url, headers=headers).status_code == 200


def test_statement_api_returns_typed_financial_projection_and_paginates(team_client):
    client = team_client
    headers, _ = owner(client)
    order, buyer, _ = confirmed(client, headers, "SO-STATEMENT")
    completed = client.post(
        "/api/v1/payments",
        headers=headers,
        json={
            "order_id": order["id"],
            "payment_number": "PAY-STATEMENT",
            "amount": "4.25",
            "payment_method": "cash",
        },
    )
    pending = client.post(
        "/api/v1/payments",
        headers=headers,
        json={
            "order_id": order["id"],
            "payment_number": "PAY-PENDING",
            "amount": "2.50",
            "payment_method": "card",
            "status": "pending",
        },
    )
    assert completed.status_code == pending.status_code == 201

    first = client.get(statement_url(buyer["id"]), headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["customer"] == {
        "id": buyer["id"],
        "name": buyer["display_name"],
        "company": buyer["company_name"],
        "email": buyer["email"],
    }
    assert body["statement"] == {
        "start_date": None,
        "end_date": None,
        "opening_balance": "0.00",
        "period_debits": "20.00",
        "period_credits": "4.25",
        "closing_balance": "15.75",
        "pending_payment_total": "2.50",
    }
    assert body["total"] == 2 and body["page"] == 1 and body["page_size"] == 20
    assert [entry["type"] for entry in body["entries"]] == ["order_charge", "payment"]
    assert body["entries"][0]["invoice_id"] is None
    assert body["entries"][0]["invoice_number"] is None
    assert all(entry["payment_number"] != "PAY-PENDING" for entry in body["entries"])

    second_page = client.get(statement_url(buyer["id"], "?page=2&page_size=1"), headers=headers)
    assert second_page.status_code == 200
    page = second_page.json()
    assert page["page"] == 2 and page["page_size"] == 1 and page["total"] == 2
    assert page["entries"][0]["type"] == "payment"
    assert page["entries"][0]["running_balance"] == "15.75"
    assert page["statement"] == body["statement"]


def test_statement_api_accepts_date_combinations_and_validates_inputs(team_client):
    client = team_client
    headers, _ = owner(client)
    buyer = create_customer(client, headers, "Date Buyer")
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    for query in (
        "",
        f"?start_date={today}",
        f"?end_date={today}",
        f"?start_date={today}&end_date={today}",
    ):
        assert client.get(statement_url(buyer["id"], query), headers=headers).status_code == 200

    for query in (
        "?page=0",
        "?page_size=0",
        "?page_size=101",
        "?start_date=not-a-date",
        "?end_date=not-a-date",
    ):
        assert client.get(statement_url(buyer["id"], query), headers=headers).status_code == 422

    invalid = client.get(
        statement_url(buyer["id"], f"?start_date={tomorrow}&end_date={today}"), headers=headers
    )
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "start_date must be on or before end_date."}


def test_statement_api_uses_safe_not_found_for_missing_foreign_and_deleted_customers(team_client):
    client = team_client
    headers, _ = owner(client)
    foreign_headers, _ = owner(client, "Beta")
    own_order, own_buyer, _ = confirmed(client, headers, "SO-OWN")
    foreign_order, foreign_buyer, _ = confirmed(client, foreign_headers, "SO-FOREIGN")
    assert invoice(client, foreign_headers, foreign_order["id"]).status_code == 201
    assert client.post(
        "/api/v1/payments",
        headers=foreign_headers,
        json={
            "order_id": foreign_order["id"],
            "payment_number": "PAY-FOREIGN",
            "amount": "5.00",
            "payment_method": "cash",
        },
    ).status_code == 201

    own = client.get(statement_url(own_buyer["id"]), headers=headers)
    assert own.status_code == 200 and own.json()["total"] == 1
    expected = {"detail": "Customer not found."}
    missing = client.get(statement_url(str(uuid4())), headers=headers)
    foreign = client.get(statement_url(foreign_buyer["id"]), headers=headers)
    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json() == expected

    deleted = create_customer(client, headers, "Deleted Statement Buyer")
    assert client.delete(f"/api/v1/customers/{deleted['id']}", headers=headers).status_code == 204
    removed = client.get(statement_url(deleted["id"]), headers=headers)
    assert removed.status_code == 404 and removed.json() == expected


def test_statement_api_exposes_optional_invoice_reference_without_requiring_it(team_client):
    client = team_client
    headers, _ = owner(client)
    first_order, first_buyer, _ = confirmed(client, headers, "SO-WITH-INVOICE")
    created = invoice(client, headers, first_order["id"])
    assert created.status_code == 201
    with_invoice = client.get(statement_url(first_buyer["id"]), headers=headers).json()
    assert with_invoice["entries"][0]["invoice_id"] == created.json()["id"]
    assert with_invoice["entries"][0]["invoice_number"] == created.json()["invoice_number"]

    second_order, second_buyer, _ = confirmed(client, headers, "SO-WITHOUT-INVOICE")
    without_invoice = client.get(statement_url(second_buyer["id"]), headers=headers)
    assert without_invoice.status_code == 200
    assert without_invoice.json()["entries"][0]["order_id"] == second_order["id"]
    assert without_invoice.json()["entries"][0]["invoice_id"] is None
    assert without_invoice.json()["entries"][0]["invoice_number"] is None
