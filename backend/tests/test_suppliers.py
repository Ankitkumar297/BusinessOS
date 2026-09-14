from uuid import uuid4

from tests.test_team import member, owner, team_client


def payload(name: str = "Global Supply", **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {"supplier_name": name, "company_name": "Global Supply Ltd", "supplier_code": "SUP-001", "tax_id": "GST-1", "registration_number": "REG-1", "contact_person_name": "Nina Rao", "email": "nina@supply.example", "phone": "123", "alternate_phone": "", "address_line_1": "1 Supply Road", "address_line_2": "", "city": "Pune", "state": "Maharashtra", "postal_code": "411001", "country": "India", "payment_terms": "Net 30", "lead_time_days": 14, "minimum_order_value": "100.00", "currency": "inr", "notes": "Preferred supplier"}
    data.update(overrides); return data


def create(client, headers, name="Global Supply", **overrides: object) -> dict:
    response = client.post("/api/v1/suppliers", headers=headers, json=payload(name, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_supplier_crud_lifecycle_filters_and_validation(team_client):
    c = team_client; headers, registration = owner(c); first = create(c, headers)
    assert first["business_id"] == registration["business"]["id"] and first["currency"] == "INR"
    second = create(c, headers, "Blue Supplier", supplier_code="SUP-002", country="USA", email="blue@supply.example", phone="999")
    assert c.get("/api/v1/suppliers?search=blue", headers=headers).json()["items"][0]["id"] == second["id"]
    assert c.get("/api/v1/suppliers?country=india", headers=headers).json()["total"] == 1
    assert c.get("/api/v1/suppliers?page_size=1&sort_by=name&sort_direction=asc", headers=headers).json()["total"] == 2
    updated = c.patch(f"/api/v1/suppliers/{first['id']}", headers=headers, json=payload("Global Updated")).json()
    assert updated["supplier_name"] == "Global Updated"
    assert c.post(f"/api/v1/suppliers/{first['id']}/deactivate", headers=headers).json()["status"] == "inactive"
    assert c.post(f"/api/v1/suppliers/{first['id']}/activate", headers=headers).json()["status"] == "active"
    assert c.delete(f"/api/v1/suppliers/{first['id']}", headers=headers).status_code == 204
    assert c.get(f"/api/v1/suppliers/{first['id']}", headers=headers).status_code == 404
    assert c.post("/api/v1/suppliers", headers=headers, json=payload(email="invalid")).status_code == 422
    assert c.post("/api/v1/suppliers", headers=headers, json=payload(lead_time_days=-1)).status_code == 422
    assert c.post("/api/v1/suppliers", headers=headers, json=payload(minimum_order_value="-1")).status_code == 422
    assert c.get("/api/v1/suppliers?status=bad&sort_by=unsafe", headers=headers).status_code == 422


def test_supplier_tenant_permissions_and_protected_fields(team_client):
    c = team_client; first, data = owner(c); second, _ = owner(c, "Beta"); supplier = create(c, first)
    assert c.get(f"/api/v1/suppliers/{supplier['id']}", headers=second).status_code == 404
    assert c.patch(f"/api/v1/suppliers/{supplier['id']}", headers=second, json=payload()).status_code == 404
    assert c.post(f"/api/v1/suppliers/{supplier['id']}/deactivate", headers=second).status_code == 404
    assert c.delete(f"/api/v1/suppliers/{supplier['id']}", headers=second).status_code == 404
    assert c.post("/api/v1/suppliers", headers=first, json=payload(business_id=data["business"]["id"])).status_code == 422
    employee = member(c, first); login = c.post("/api/v1/auth/login", json={"email": employee["email"], "password": "StrongPassword123!"}).json(); denied = {"Authorization": "Bearer " + login["access_token"]}
    assert c.get("/api/v1/suppliers", headers=denied).status_code == 403
    assert c.post("/api/v1/suppliers", headers=denied, json=payload()).status_code == 403
    assert c.patch(f"/api/v1/suppliers/{supplier['id']}", headers=denied, json=payload()).status_code == 403
    assert c.post(f"/api/v1/suppliers/{supplier['id']}/deactivate", headers=denied).status_code == 403
    assert c.delete(f"/api/v1/suppliers/{supplier['id']}", headers=denied).status_code == 403
