from datetime import date
from unittest.mock import Mock, patch
from uuid import UUID

import pytest

from app.main import app
from app.services.report_export_service import PreparedCsvExport
from tests.test_team import member, owner, team_client


def test_orders_export_requires_authentication_and_reports_permission(team_client):
    client = team_client
    assert client.get("/api/v1/reports/orders/export").status_code == 401
    headers, _ = owner(client)
    employee = member(client, headers)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": employee["email"], "password": "StrongPassword123!"},
    ).json()
    denied = {"Authorization": "Bearer " + login["access_token"]}
    assert client.get("/api/v1/reports/orders/export", headers=denied).status_code == 403


def test_orders_export_headers_and_filters_reach_export_service(team_client):
    client = team_client
    headers, _ = owner(client)
    customer_id = UUID("12345678-1234-5678-1234-567812345678")
    exporter = Mock()
    exporter.orders.return_value = PreparedCsvExport(["Order ID,Order Number\r\n"])
    with patch("app.api.routes.report_exports.ReportExportService", return_value=exporter):
        response = client.get(
            "/api/v1/reports/orders/export",
            headers=headers,
            params={"start_date": "2026-09-01", "end_date": "2026-09-11", "status": "confirmed", "customer_id": str(customer_id), "search": "  SO-1  "},
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="orders-report.csv"'
    assert response.text == "Order ID,Order Number\r\n"
    exporter.orders.assert_called_once_with(
        date(2026, 9, 1), date(2026, 9, 11), "confirmed", customer_id, "SO-1"
    )


@pytest.mark.parametrize(("report", "method", "filename"), [
    ("payments", "payments", "payments-report.csv"),
    ("inventory", "inventory", "inventory-report.csv"),
    ("customers", "customers", "customers-report.csv"),
])
def test_other_exports_return_csv_attachment_headers(team_client, report, method, filename):
    client = team_client
    headers, _ = owner(client)
    exporter = Mock()
    getattr(exporter, method).return_value = PreparedCsvExport(["Header\r\n"])
    with patch("app.api.routes.report_exports.ReportExportService", return_value=exporter):
        response = client.get(f"/api/v1/reports/{report}/export", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'


def test_export_contract_does_not_expose_pagination():
    schema = app.openapi()
    for report in ("orders", "payments", "inventory", "customers"):
        parameters = schema["paths"][f"/api/v1/reports/{report}/export"]["get"]["parameters"]
        names = {parameter["name"] for parameter in parameters}
        assert "page" not in names
        assert "page_size" not in names


def test_invalid_dates_and_enums_fail_before_streaming(team_client):
    client = team_client
    headers, _ = owner(client)
    invalid_range = client.get(
        "/api/v1/reports/orders/export?start_date=2026-09-12&end_date=2026-09-11",
        headers=headers,
    )
    assert invalid_range.status_code == 422
    assert invalid_range.headers["content-type"].startswith("application/json")
    invalid_status = client.get(
        "/api/v1/reports/payments/export?status=unknown",
        headers=headers,
    )
    assert invalid_status.status_code == 422
    assert invalid_status.headers["content-type"].startswith("application/json")


def test_empty_export_is_header_only_and_json_reports_remain_unchanged(team_client):
    client = team_client
    headers, _ = owner(client)
    exported = client.get("/api/v1/reports/orders/export", headers=headers)
    assert exported.status_code == 200
    assert exported.text == "Order ID,Order Number,Customer ID,Customer Name,Status,Order Date,Subtotal,Tax Total,Grand Total,Item Count\r\n"
    report = client.get("/api/v1/reports/orders", headers=headers)
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("application/json")
    assert report.json() == {
        "items": [],
        "summary": {"matching_orders": 0, "confirmed_order_count": 0, "confirmed_order_value": "0.00"},
        "total": 0,
        "page": 1,
        "page_size": 20,
    }
