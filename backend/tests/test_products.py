from tests.test_suppliers import create as create_supplier
from tests.test_team import member, owner, team_client


def payload(name: str = "Widget", **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {"name": name, "sku": "WID-001", "barcode": "123456", "description": "Useful widget", "category": "Tools", "brand": "Acme", "unit_of_measure": "piece", "selling_price": "19.99", "cost_price": "10.50", "tax_rate": "18", "track_inventory": True, "reorder_level": "5.000", "notes": "Keep dry"}
    data.update(overrides); return data


def create(client, headers, name="Widget", **overrides: object) -> dict:
    response = client.post("/api/v1/products", headers=headers, json=payload(name, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_product_crud_list_lifecycle_and_validation(team_client):
    c = team_client; headers, registration = owner(c); first = create(c, headers)
    assert first["business_id"] == registration["business"]["id"] and first["selling_price"] == "19.99" and "current_stock" not in first
    second = create(c, headers, "Blue Widget", sku="WID-002", barcode="123457", category="Parts", track_inventory=False)
    assert c.get("/api/v1/products?search=blue", headers=headers).json()["items"][0]["id"] == second["id"]
    assert c.get("/api/v1/products?category=tools&track_inventory=true&sort_by=name", headers=headers).json()["total"] == 1
    updated = c.patch(f"/api/v1/products/{first['id']}", headers=headers, json=payload("Widget 2")).json(); assert updated["name"] == "Widget 2"
    assert c.post(f"/api/v1/products/{first['id']}/deactivate", headers=headers).json()["status"] == "inactive"
    assert c.post(f"/api/v1/products/{first['id']}/activate", headers=headers).json()["status"] == "active"
    assert c.delete(f"/api/v1/products/{first['id']}", headers=headers).status_code == 204
    assert c.get(f"/api/v1/products/{first['id']}", headers=headers).status_code == 404
    assert c.post("/api/v1/products", headers=headers, json=payload(selling_price="-1")).status_code == 422
    assert c.post("/api/v1/products", headers=headers, json=payload(tax_rate="101")).status_code == 422
    assert c.get("/api/v1/products?sort_by=unsafe", headers=headers).status_code == 422


def test_product_tenant_sku_permission_and_supplier_links(team_client):
    c = team_client; first, data = owner(c); second, second_data = owner(c, "Beta"); product = create(c, first); supplier = create_supplier(c, first)
    assert c.post(f"/api/v1/products/{product['id']}/suppliers", headers=first, json={"supplier_id": supplier["id"], "purchase_cost": "8.00", "is_primary": True}).status_code == 201
    assert c.get(f"/api/v1/products/{product['id']}/suppliers", headers=first).json()[0]["supplier_name"] == supplier["supplier_name"]
    assert c.post(f"/api/v1/products/{product['id']}/suppliers", headers=first, json={"supplier_id": supplier["id"]}).status_code == 409
    foreign_supplier = create_supplier(c, second, supplier_code="OTHER")
    assert c.post(f"/api/v1/products/{product['id']}/suppliers", headers=first, json={"supplier_id": foreign_supplier["id"]}).status_code == 404
    assert c.delete(f"/api/v1/products/{product['id']}/suppliers/{supplier['id']}", headers=first).status_code == 204
    assert c.get(f"/api/v1/products/{product['id']}", headers=second).status_code == 404
    assert c.patch(f"/api/v1/products/{product['id']}", headers=second, json=payload()).status_code == 404
    assert c.post("/api/v1/products", headers=first, json=payload(business_id=data["business"]["id"])).status_code == 422
    assert c.post("/api/v1/products", headers=second, json=payload()).status_code == 201
    assert c.post("/api/v1/products", headers=first, json=payload()).status_code == 409
    employee = member(c, first); login = c.post("/api/v1/auth/login", json={"email": employee["email"], "password": "StrongPassword123!"}).json(); denied = {"Authorization": "Bearer " + login["access_token"]}
    assert c.get("/api/v1/products", headers=denied).status_code == 403
    assert c.post("/api/v1/products", headers=denied, json=payload()).status_code == 403
