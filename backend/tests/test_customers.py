from uuid import uuid4

from tests.test_team import member, owner, team_client


def payload(name: str = "Ava Patel", **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "customer_type": "individual", "display_name": name, "company_name": "Northwind Ltd",
        "email": f"{name.replace(' ', '.').lower()}@example.com", "phone": "+91 9876543210",
        "alternate_phone": "", "address_line_1": "1 Market Street", "address_line_2": "",
        "city": "Mumbai", "state": "Maharashtra", "postal_code": "400001", "country": "India",
        "tax_id": "GSTIN-123", "notes": "Priority account",
    }
    data.update(overrides)
    return data


def create(client, headers, name: str = "Ava Patel", **overrides: object) -> dict:
    response = client.post("/api/v1/customers", headers=headers, json=payload(name, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_customer_crud_status_and_validation(team_client):
    c = team_client; headers, registered = owner(c)
    customer = create(c, headers)
    assert customer["business_id"] == registered["business"]["id"]
    assert customer["alternate_phone"] is None
    assert c.get(f"/api/v1/customers/{customer['id']}", headers=headers).status_code == 200
    updated = c.patch(f"/api/v1/customers/{customer['id']}", headers=headers,
                      json=payload("Ava Updated", customer_type="business", company_name="Acme Pvt Ltd")).json()
    assert updated["display_name"] == "Ava Updated" and updated["customer_type"] == "business"
    assert c.post(f"/api/v1/customers/{customer['id']}/deactivate", headers=headers).json()["status"] == "inactive"
    assert c.post(f"/api/v1/customers/{customer['id']}/activate", headers=headers).json()["status"] == "active"
    assert c.delete(f"/api/v1/customers/{customer['id']}", headers=headers).status_code == 204
    assert c.get(f"/api/v1/customers/{customer['id']}", headers=headers).status_code == 404
    assert c.get("/api/v1/customers", headers=headers).json()["total"] == 0
    assert c.post("/api/v1/customers", headers=headers, json=payload(email="not-an-email")).status_code == 422
    assert c.post("/api/v1/customers", headers=headers, json=payload(customer_type="unknown")).status_code == 422
    assert c.get("/api/v1/customers?status=unknown", headers=headers).status_code == 422
    assert c.get("/api/v1/customers?sort_by=unsafe", headers=headers).status_code == 422
    assert c.get("/api/v1/customers?page_size=101", headers=headers).status_code == 422


def test_customer_list_search_filters_pagination_and_permissions(team_client):
    c = team_client; headers, _ = owner(c)
    first = create(c, headers, "Ava Patel", customer_type="individual", company_name="Apex", phone="111")
    create(c, headers, "Ben Stone", customer_type="business", company_name="Blue Sky", phone="222")
    create(c, headers, "Cara West", customer_type="business", company_name="Cedar", phone="333")
    assert c.get("/api/v1/customers?search=blue", headers=headers).json()["items"][0]["display_name"] == "Ben Stone"
    assert c.get("/api/v1/customers?search=111", headers=headers).json()["total"] == 1
    assert c.get("/api/v1/customers?customer_type=business", headers=headers).json()["total"] == 2
    assert c.post(f"/api/v1/customers/{first['id']}/deactivate", headers=headers).status_code == 200
    assert c.get("/api/v1/customers?status=inactive", headers=headers).json()["total"] == 1
    page = c.get("/api/v1/customers?page_size=1&sort_by=name&sort_direction=asc", headers=headers).json()
    assert page["total"] == 3 and page["items"][0]["display_name"] == "Ava Patel"
    employee = member(c, headers)
    login = c.post("/api/v1/auth/login", json={"email": employee["email"], "password": "StrongPassword123!"}).json()
    denied = {"Authorization": "Bearer " + login["access_token"]}
    assert c.get("/api/v1/customers", headers=denied).status_code == 403
    assert c.post("/api/v1/customers", headers=denied, json=payload()).status_code == 403
    assert c.patch(f"/api/v1/customers/{first['id']}", headers=denied, json=payload("No Access")).status_code == 403
    assert c.post(f"/api/v1/customers/{first['id']}/deactivate", headers=denied).status_code == 403
    assert c.delete(f"/api/v1/customers/{first['id']}", headers=denied).status_code == 403


def test_customer_tenant_isolation_and_protected_fields(team_client):
    c = team_client; first, first_data = owner(c); second, _ = owner(c, "Beta")
    customer = create(c, first, "Private Customer")
    assert c.get(f"/api/v1/customers/{customer['id']}", headers=second).status_code == 404
    assert c.patch(f"/api/v1/customers/{customer['id']}", headers=second, json=payload("Stolen")).status_code == 404
    assert c.post(f"/api/v1/customers/{customer['id']}/deactivate", headers=second).status_code == 404
    assert c.delete(f"/api/v1/customers/{customer['id']}", headers=second).status_code == 404
    unsafe = payload("Private Customer", business_id=str(uuid4()))
    assert c.patch(f"/api/v1/customers/{customer['id']}", headers=first, json=unsafe).status_code == 422
    assert c.post("/api/v1/customers", headers=first, json=payload("Bad Owner", business_id=first_data["business"]["id"])).status_code == 422
