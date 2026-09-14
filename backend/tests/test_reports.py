from datetime import date, timedelta

from tests.test_customers import create as create_customer
from tests.test_inventory import adjust
from tests.test_invoices import confirmed
from tests.test_orders import create as create_order
from tests.test_products import create as create_product
from tests.test_team import member, owner, team_client


def test_reports_require_auth_permission_validate_dates_and_support_empty_results(team_client):
    client = team_client
    assert client.get("/api/v1/reports/orders").status_code == 401
    headers, _ = owner(client)
    for report in ("orders", "payments", "inventory", "customers"):
        response = client.get(f"/api/v1/reports/{report}", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
        assert response.json()["total"] == 0

    employee = member(client, headers)
    login = client.post("/api/v1/auth/login", json={"email": employee["email"], "password": "StrongPassword123!"}).json()
    denied = {"Authorization": "Bearer " + login["access_token"]}
    for report in ("orders", "payments", "inventory", "customers"):
        assert client.get(f"/api/v1/reports/{report}", headers=denied).status_code == 403

    assert client.get("/api/v1/reports/orders?start_date=2026-02-02&end_date=2026-02-01", headers=headers).status_code == 422
    assert client.get("/api/v1/reports/payments?status=unknown", headers=headers).status_code == 422
    assert client.get("/api/v1/reports/inventory?page_size=101", headers=headers).status_code == 422


def test_order_and_payment_reports_filter_paginate_aggregate_and_isolate_tenants(team_client):
    client = team_client
    headers, _ = owner(client)
    foreign_headers, _ = owner(client, "Beta")
    order, customer, product = confirmed(client, headers, "SO-REPORT-A")
    create_order(client, headers, customer["id"], product["id"], order_number="SO-REPORT-DRAFT")
    assert client.post("/api/v1/payments", headers=headers, json={"order_id": order["id"], "payment_number": "PAY-REPORT-C", "amount": "5.10", "payment_method": "cash"}).status_code == 201
    assert client.post("/api/v1/payments", headers=headers, json={"order_id": order["id"], "payment_number": "PAY-REPORT-P", "amount": "2.20", "payment_method": "card", "status": "pending"}).status_code == 201
    foreign_order, _, _ = confirmed(client, foreign_headers, "SO-REPORT-BETA")
    assert client.post("/api/v1/payments", headers=foreign_headers, json={"order_id": foreign_order["id"], "payment_number": "PAY-BETA", "amount": "9.00", "payment_method": "cash"}).status_code == 201

    orders = client.get("/api/v1/reports/orders?page_size=1", headers=headers).json()
    assert orders["total"] == 2 and len(orders["items"]) == 1
    assert orders["summary"] == {"matching_orders": 2, "confirmed_order_count": 1, "confirmed_order_value": "20.00"}
    filtered_orders = client.get(f"/api/v1/reports/orders?status=confirmed&customer_id={customer['id']}&search=REPORT-A", headers=headers).json()
    assert filtered_orders["total"] == 1 and filtered_orders["items"][0]["item_count"] == 1
    assert filtered_orders["items"][0]["grand_total"] == "20.00"

    payments = client.get("/api/v1/reports/payments", headers=headers).json()
    assert payments["total"] == 2
    assert payments["summary"]["completed_amount"] == "5.10"
    assert payments["summary"]["pending_amount"] == "2.20"
    assert payments["summary"]["completed_count"] == payments["summary"]["pending_count"] == 1
    cash = client.get(f"/api/v1/reports/payments?payment_method=cash&order_id={order['id']}&search=PAY-REPORT", headers=headers).json()
    assert cash["total"] == 1 and cash["items"][0]["amount"] == "5.10"
    pending_only = client.get("/api/v1/reports/payments?status=pending", headers=headers).json()
    assert pending_only["total"] == 1 and pending_only["summary"]["pending_amount"] == "2.20"
    assert client.get(f"/api/v1/reports/orders?customer_id={foreign_order['customer_id']}", headers=headers).json()["total"] == 0
    assert client.get(f"/api/v1/reports/payments?order_id={foreign_order['id']}", headers=headers).json()["total"] == 0

    today = date.today().isoformat()
    assert client.get(f"/api/v1/reports/orders?start_date={today}&end_date={today}", headers=headers).json()["total"] == 2
    future = (date.today() + timedelta(days=1)).isoformat()
    assert client.get(f"/api/v1/reports/payments?start_date={future}", headers=headers).json()["total"] == 0
    assert client.get("/api/v1/reports/orders", headers=foreign_headers).json()["total"] == 1
    assert client.get("/api/v1/reports/payments", headers=foreign_headers).json()["total"] == 1


def test_inventory_report_uses_canonical_stock_status_filters_search_and_tenant_scope(team_client):
    client = team_client
    headers, _ = owner(client)
    foreign_headers, _ = owner(client, "Beta")
    stocked = create_product(client, headers, "Stocked", sku="REP-STOCK", barcode="REP-STOCK", reorder_level="5")
    low = create_product(client, headers, "Low stock", sku="REP-LOW", barcode="REP-LOW", reorder_level="5")
    create_product(client, headers, "No stock", sku="REP-EMPTY", barcode="REP-EMPTY", reorder_level="5")
    create_product(client, headers, "Untracked", sku="REP-OFF", barcode="REP-OFF", track_inventory=False)
    adjust(client, headers, stocked["id"], "opening_balance", "10")
    adjust(client, headers, low["id"], "opening_balance", "3")
    create_product(client, foreign_headers, "Foreign", sku="REP-FOREIGN", barcode="REP-FOREIGN", reorder_level="5")

    report = client.get("/api/v1/reports/inventory?page_size=2", headers=headers).json()
    assert report["total"] == 3 and len(report["items"]) == 2
    assert report["summary"] == {"tracked_products": 3, "in_stock_count": 1, "low_stock_count": 1, "out_of_stock_count": 1}
    low_only = client.get("/api/v1/reports/inventory?status=low_stock&search=Low", headers=headers).json()
    assert low_only["total"] == 1
    assert low_only["items"][0]["product_id"] == low["id"]
    assert low_only["items"][0]["quantity"] == "3.000"
    assert low_only["items"][0]["stock_status"] == "low_stock"
    assert client.get("/api/v1/reports/inventory", headers=foreign_headers).json()["total"] == 1


def test_customer_report_filters_searches_and_aggregates_confirmed_order_value(team_client):
    client = team_client
    headers, _ = owner(client)
    foreign_headers, _ = owner(client, "Beta")
    order, customer, _ = confirmed(client, headers, "SO-CUSTOMER-REPORT")
    inactive = create_customer(client, headers, "Inactive Report Customer")
    assert client.post(f"/api/v1/customers/{inactive['id']}/deactivate", headers=headers).status_code == 200
    create_customer(client, foreign_headers, "Foreign Report Customer")

    report = client.get("/api/v1/reports/customers?page_size=1", headers=headers).json()
    assert report["total"] == 2 and len(report["items"]) == 1
    assert report["summary"] == {"matching_customers": 2, "active_count": 1, "inactive_count": 1, "confirmed_order_value": "20.00"}
    active = client.get("/api/v1/reports/customers?status=active&search=Ava", headers=headers).json()
    assert active["total"] == 1
    assert active["items"][0]["customer_id"] == customer["id"]
    assert active["items"][0]["order_count"] == 1
    assert active["items"][0]["confirmed_order_value"] == "20.00"
    inactive_only = client.get("/api/v1/reports/customers?status=inactive&search=Inactive", headers=headers).json()
    assert inactive_only["total"] == 1 and inactive_only["summary"]["inactive_count"] == 1
    today = date.today().isoformat()
    assert client.get(f"/api/v1/reports/customers?start_date={today}&end_date={today}", headers=headers).json()["total"] == 2
    future = (date.today() + timedelta(days=1)).isoformat()
    assert client.get(f"/api/v1/reports/customers?start_date={future}", headers=headers).json()["total"] == 0
    assert client.get("/api/v1/reports/customers", headers=foreign_headers).json()["total"] == 1
