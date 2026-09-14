"""Focused local tests for atomic Order audit integration."""
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Inventory, Order, StockMovement
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.order_service import OrderService
from tests.test_audit_customer_integration import context_for
from tests.test_customers import create as create_customer
from tests.test_inventory import adjust
from tests.test_orders import create as create_order, payload as order_payload
from tests.test_products import create as create_product
from tests.test_team import owner, team_client


def audits(client, business_id: str, entity_type: str) -> list[AuditLog]:
    with Session(client.test_engine) as session:
        return list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.business_id == UUID(business_id),
                    AuditLog.entity_type == entity_type,
                ).order_by(AuditLog.created_at, AuditLog.id)
            )
        )


def order_state(client, order_id: str, product_ids: list[str]) -> tuple[str, dict[str, Decimal], list[StockMovement]]:
    with Session(client.test_engine) as session:
        order = session.get(Order, UUID(order_id))
        assert order is not None
        inventories = list(
            session.scalars(
                select(Inventory).where(
                    Inventory.product_id.in_([UUID(product_id) for product_id in product_ids])
                )
            )
        )
        quantities = {str(row.product_id): row.quantity_on_hand for row in inventories}
        movements = list(
            session.scalars(
                select(StockMovement).where(
                    StockMovement.product_id.in_([UUID(product_id) for product_id in product_ids])
                )
            )
        )
        return order.status, quantities, movements


def create_two_item_order(client, headers, number: str, first_stock: str = "5", second_stock: str = "5"):
    customer = create_customer(client, headers, f"Customer {number}")
    first = create_product(client, headers, f"First {number}", sku=f"A-{number}", barcode=f"A-{number}")
    second = create_product(client, headers, f"Second {number}", sku=f"B-{number}", barcode=f"B-{number}")
    assert adjust(client, headers, first["id"], "opening_balance", first_stock).status_code == 200
    assert adjust(client, headers, second["id"], "opening_balance", second_stock).status_code == 200
    order = create_order(
        client,
        headers,
        customer["id"],
        first["id"],
        order_number=number,
        items=[
            {"product_id": first["id"], "quantity": "2"},
            {"product_id": second["id"], "quantity": "2"},
        ],
    )
    return order, first, second


def test_order_create_update_noop_and_cancel_have_exact_semantic_audits(team_client):
    headers, registration = owner(team_client)
    customer = create_customer(team_client, headers, "Order Audit Customer")
    product = create_product(team_client, headers, sku="ORDER-AUD", barcode="ORDER-AUD")
    order = create_order(
        team_client, headers, customer["id"], product["id"], order_number="SO-AUDIT-1"
    )

    rows = audits(team_client, registration["business"]["id"], "order")
    assert len(rows) == 1
    assert rows[0].action == "order.created"
    assert rows[0].entity_type == "order"
    assert rows[0].entity_id == UUID(order["id"])
    assert rows[0].entity_display == "SO-AUDIT-1"
    assert rows[0].business_id == UUID(registration["business"]["id"])
    assert rows[0].actor_user_id == UUID(registration["user"]["id"])
    assert rows[0].changed_fields == [
        "customer_id", "items", "notes", "order_date", "order_number"
    ]

    changed_payload = order_payload(
        customer["id"], product["id"], order_number="SO-AUDIT-2",
        items=[{"product_id": product["id"], "quantity": "3"}],
    )
    assert team_client.patch(
        f"/api/v1/orders/{order['id']}", headers=headers, json=changed_payload
    ).status_code == 200
    assert team_client.patch(
        f"/api/v1/orders/{order['id']}", headers=headers, json=changed_payload
    ).status_code == 200
    assert team_client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=headers
    ).status_code == 200

    rows = audits(team_client, registration["business"]["id"], "order")
    assert [row.action for row in rows].count("order.created") == 1
    assert [row.action for row in rows].count("order.updated") == 2
    assert [row.action for row in rows].count("order.cancelled") == 1
    updates = [row for row in rows if row.action == "order.updated"]
    assert sorted(tuple(row.changed_fields) for row in updates) == [(), ("items", "order_number")]
    cancelled = [row for row in rows if row.action == "order.cancelled"]
    assert len(cancelled) == 1
    assert cancelled[0].changed_fields == ["status"]


def test_multi_item_confirmation_has_one_order_audit_and_no_inventory_audit(team_client):
    headers, registration = owner(team_client)
    order, first, second = create_two_item_order(team_client, headers, "SO-MULTI-AUDIT")
    inventory_audit_baseline = len(audits(team_client, registration["business"]["id"], "inventory"))

    response = team_client.post(f"/api/v1/orders/{order['id']}/confirm", headers=headers)
    assert response.status_code == 200, response.text
    status, quantities, movements = order_state(
        team_client, order["id"], [first["id"], second["id"]]
    )
    assert status == "confirmed"
    assert quantities == {first["id"]: Decimal("3"), second["id"]: Decimal("3")}
    confirmation_movements = [
        movement for movement in movements
        if movement.reason == f"Order {order['order_number']} confirmed"
    ]
    assert len(confirmation_movements) == 2

    order_rows = audits(team_client, registration["business"]["id"], "order")
    confirmed = [row for row in order_rows if row.action == "order.confirmed"]
    assert len(confirmed) == 1
    assert confirmed[0].entity_id == UUID(order["id"])
    assert confirmed[0].changed_fields == ["status"]
    assert len(audits(team_client, registration["business"]["id"], "inventory")) == inventory_audit_baseline


def test_cross_tenant_and_invalid_lifecycle_failures_create_no_order_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    customer = create_customer(team_client, first_headers, "Private Order Customer")
    product = create_product(team_client, first_headers, sku="PRIVATE-ORDER", barcode="PRIVATE-ORDER")
    order = create_order(team_client, first_headers, customer["id"], product["id"], order_number="SO-PRIVATE")
    baseline = len(audits(team_client, first["business"]["id"], "order"))

    assert team_client.post(f"/api/v1/orders/{order['id']}/confirm", headers=second_headers).status_code == 404
    assert team_client.post(f"/api/v1/orders/{order['id']}/cancel", headers=first_headers).status_code == 200
    after_cancel = len(audits(team_client, first["business"]["id"], "order"))
    assert after_cancel == baseline + 1
    assert team_client.post(f"/api/v1/orders/{order['id']}/confirm", headers=first_headers).status_code == 409
    assert len(audits(team_client, first["business"]["id"], "order")) == after_cancel
    assert audits(team_client, second["business"]["id"], "order") == []


def test_insufficient_stock_rolls_back_earlier_item_and_creates_no_confirmation_audit(team_client):
    headers, registration = owner(team_client)
    order, first, second = create_two_item_order(
        team_client, headers, "SO-INSUFFICIENT-AUDIT", first_stock="5", second_stock="1"
    )
    order_audit_baseline = len(audits(team_client, registration["business"]["id"], "order"))
    inventory_audit_baseline = len(audits(team_client, registration["business"]["id"], "inventory"))

    response = team_client.post(f"/api/v1/orders/{order['id']}/confirm", headers=headers)
    assert response.status_code == 409
    status, quantities, movements = order_state(
        team_client, order["id"], [first["id"], second["id"]]
    )
    assert status == "draft"
    assert quantities == {first["id"]: Decimal("5"), second["id"]: Decimal("1")}
    assert all(movement.reason != f"Order {order['order_number']} confirmed" for movement in movements)
    assert len(audits(team_client, registration["business"]["id"], "order")) == order_audit_baseline
    assert len(audits(team_client, registration["business"]["id"], "inventory")) == inventory_audit_baseline


def test_forced_confirmation_audit_failure_rolls_back_order_inventory_and_movements(team_client, monkeypatch):
    headers, registration = owner(team_client)
    order, first, second = create_two_item_order(team_client, headers, "SO-AUDIT-FAILURE")
    context = context_for(team_client, registration["business"]["id"])
    baseline = len(audits(team_client, registration["business"]["id"], "order"))

    def fail_record(self: AuditService, **_: object) -> AuditLog:
        raise AuditPersistenceError("forced order audit failure")

    monkeypatch.setattr(AuditService, "record", fail_record)
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError, match="forced order audit failure"):
            OrderService(session, context).confirm(UUID(order["id"]))
    finally:
        session.close()

    status, quantities, movements = order_state(
        team_client, order["id"], [first["id"], second["id"]]
    )
    assert status == "draft"
    assert quantities == {first["id"]: Decimal("5"), second["id"]: Decimal("5")}
    assert all(movement.reason != f"Order {order['order_number']} confirmed" for movement in movements)
    assert len(audits(team_client, registration["business"]["id"], "order")) == baseline


def test_confirmation_commit_failure_rolls_back_all_domain_and_audit_rows(team_client, monkeypatch):
    headers, registration = owner(team_client)
    order, first, second = create_two_item_order(team_client, headers, "SO-COMMIT-FAILURE")
    context = context_for(team_client, registration["business"]["id"])
    baseline = len(audits(team_client, registration["business"]["id"], "order"))
    session = Session(team_client.test_engine)
    monkeypatch.setattr(
        session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("forced order commit failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="forced order commit failure"):
            OrderService(session, context).confirm(UUID(order["id"]))
    finally:
        session.close()

    status, quantities, movements = order_state(
        team_client, order["id"], [first["id"], second["id"]]
    )
    assert status == "draft"
    assert quantities == {first["id"]: Decimal("5"), second["id"]: Decimal("5")}
    assert all(movement.reason != f"Order {order['order_number']} confirmed" for movement in movements)
    assert len(audits(team_client, registration["business"]["id"], "order")) == baseline
