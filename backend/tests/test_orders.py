from tests.test_customers import create as create_customer
from tests.test_inventory import adjust
from tests.test_products import create as create_product
from tests.test_team import member, owner, team_client


def payload(customer_id: str, product_id: str, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {"customer_id": customer_id, "order_number": "SO-1001", "notes": "Priority", "items": [{"product_id": product_id, "quantity": "2.000"}]}
    data.update(overrides); return data


def create(client, headers, customer_id: str, product_id: str, **overrides: object) -> dict:
    response = client.post("/api/v1/orders", headers=headers, json=payload(customer_id, product_id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_order_draft_totals_lifecycle_inventory_and_tenant_scope(team_client):
    c = team_client; first, _ = owner(c); second, _ = owner(c, "Beta")
    customer = create_customer(c, first); product = create_product(c, first, selling_price="10.00", tax_rate="10")
    draft = create(c, first, customer["id"], product["id"])
    assert draft["status"] == "draft" and draft["subtotal"] == "20.00" and draft["tax_total"] == "2.00" and draft["grand_total"] == "22.00"
    assert c.get("/api/v1/orders?search=SO-1001", headers=first).json()["total"] == 1
    assert c.get(f"/api/v1/orders/{draft['id']}", headers=second).status_code == 404
    foreign_customer = create_customer(c, second, "Other customer")
    assert c.post("/api/v1/orders", headers=first, json=payload(foreign_customer["id"], product["id"], order_number="SO-1002")).status_code == 404
    adjust(c, first, product["id"], "opening_balance", "5")
    confirmed = c.post(f"/api/v1/orders/{draft['id']}/confirm", headers=first)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    assert c.get(f"/api/v1/inventory/{product['id']}", headers=first).json()["quantity_on_hand"] == "3.000"
    assert c.patch(f"/api/v1/orders/{draft['id']}", headers=first, json=payload(customer["id"], product["id"])).status_code == 409
    assert c.post(f"/api/v1/orders/{draft['id']}/cancel", headers=first).status_code == 409


def test_order_permissions_and_multi_item_confirmation_rolls_back(team_client):
    c = team_client; headers, _ = owner(c); customer = create_customer(c, headers); first = create_product(c, headers, sku="ONE", barcode="ONE"); second = create_product(c, headers, sku="TWO", barcode="TWO")
    adjust(c, headers, first["id"], "opening_balance", "5"); adjust(c, headers, second["id"], "opening_balance", "1")
    order = create(c, headers, customer["id"], first["id"], items=[{"product_id": first["id"], "quantity": "2"}, {"product_id": second["id"], "quantity": "2"}])
    response = c.post(f"/api/v1/orders/{order['id']}/confirm", headers=headers)
    assert response.status_code == 409
    assert c.get(f"/api/v1/inventory/{first['id']}", headers=headers).json()["quantity_on_hand"] == "5.000"
    assert c.get(f"/api/v1/orders/{order['id']}", headers=headers).json()["status"] == "draft"
    employee = member(c, headers); login = c.post("/api/v1/auth/login", json={"email": employee["email"], "password": "StrongPassword123!"}).json(); denied = {"Authorization": "Bearer " + login["access_token"]}
    assert c.get("/api/v1/orders", headers=denied).status_code == 403
