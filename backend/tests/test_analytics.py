from tests.test_customers import create as create_customer
from tests.test_inventory import adjust
from tests.test_invoices import confirmed, invoice
from tests.test_orders import create as create_order
from tests.test_products import create as create_product
from tests.test_team import member, owner, team_client


def test_dashboard_requires_auth_permission_and_empty_business_is_valid(team_client):
    client = team_client
    assert client.get("/api/v1/analytics/dashboard").status_code == 401
    headers, _ = owner(client)
    response = client.get("/api/v1/analytics/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["range"] == "30d"
    assert body["summary"] == {"total_customers": 0, "total_products": 0, "total_orders": 0, "total_invoices": 0}
    assert body["orders"]["period_confirmed_order_value"] == "0.00"
    assert body["inventory"]["low_stock_products"] == []
    employee = member(client, headers)
    login = client.post("/api/v1/auth/login", json={"email": employee["email"], "password": "StrongPassword123!"}).json()
    denied = {"Authorization": "Bearer " + login["access_token"]}
    assert client.get("/api/v1/analytics/dashboard", headers=denied).status_code == 403
    assert client.get("/api/v1/analytics/dashboard?range=365d", headers=headers).status_code == 422


def test_dashboard_aggregates_authoritative_values_and_inventory_semantics(team_client):
    client = team_client
    headers, _ = owner(client)
    order, customer, product = confirmed(client, headers, "SO-ANALYTICS")
    issued = invoice(client, headers, order["id"])
    assert issued.status_code == 201, issued.text
    completed = client.post("/api/v1/payments", headers=headers, json={"order_id": order["id"], "payment_number": "PAY-A", "amount": "5.00", "payment_method": "cash"})
    pending = client.post("/api/v1/payments", headers=headers, json={"order_id": order["id"], "payment_number": "PAY-P", "amount": "2.00", "payment_method": "cash", "status": "pending"})
    assert completed.status_code == pending.status_code == 201
    create_order(client, headers, customer["id"], product["id"], order_number="SO-DRAFT")
    low = create_product(client, headers, "Low Widget", sku="LOW-1", barcode="LOW-1", reorder_level="5")
    adjust(client, headers, low["id"], "opening_balance", "3")
    create_product(client, headers, "Empty Widget", sku="EMPTY-1", barcode="EMPTY-1", reorder_level="5")

    body = client.get("/api/v1/analytics/dashboard?range=7d", headers=headers).json()
    assert body["summary"] == {"total_customers": 1, "total_products": 3, "total_orders": 2, "total_invoices": 1}
    assert body["customers"] == {"total": 1, "active": 1, "inactive": 0}
    assert body["orders"]["draft_count"] == 1 and body["orders"]["confirmed_count"] == 1
    assert body["orders"]["period_confirmed_order_value"] == "20.00"
    assert body["orders"]["period_average_confirmed_order_value"] == "20.00"
    assert body["payments"]["period_completed_amount"] == "5.00"
    assert body["payments"]["period_pending_amount"] == "2.00"
    assert body["payments"]["outstanding_amount"] == "15.00"
    assert body["inventory"]["tracked_products"] == 3
    assert body["inventory"]["in_stock_count"] == 1
    assert body["inventory"]["low_stock_count"] == 1
    assert body["inventory"]["out_of_stock_count"] == 1
    assert {item["stock_status"] for item in body["inventory"]["low_stock_products"]} == {"low_stock", "out_of_stock"}
    assert body["recent_activity"]["orders"][0]["reference"] == "SO-DRAFT"
    assert body["recent_activity"]["payments"][0]["reference"] in {"PAY-A", "PAY-P"}
    assert body["recent_activity"]["invoices"][0]["reference"] == "INV-000001"


def test_dashboard_never_aggregates_another_business(team_client):
    client = team_client
    first, _ = owner(client)
    second, _ = owner(client, "Beta")
    own_order, _, _ = confirmed(client, first, "SO-ALPHA")
    invoice(client, first, own_order["id"])
    foreign_order, _, _ = confirmed(client, second, "SO-BETA")
    invoice(client, second, foreign_order["id"])
    client.post("/api/v1/payments", headers=second, json={"order_id": foreign_order["id"], "payment_number": "PAY-BETA", "amount": "10.00", "payment_method": "cash"})

    body = client.get("/api/v1/analytics/dashboard", headers=first).json()
    assert body["summary"] == {"total_customers": 1, "total_products": 1, "total_orders": 1, "total_invoices": 1}
    assert body["orders"]["period_confirmed_order_value"] == "20.00"
    assert body["payments"]["period_completed_amount"] == "0.00"
    assert all(record["reference"] != "SO-BETA" for record in body["recent_activity"]["orders"])
    assert all(record["reference"] != "PAY-BETA" for record in body["recent_activity"]["payments"])
