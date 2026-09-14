"""Real PostgreSQL transaction proofs for Order audit integration."""
import os
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, Inventory, Order, StockMovement
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.order_service import OrderService
from tests.test_audit_customer_integration import context_for
from tests.test_audit_order_integration import audits, create_two_item_order, order_state
from tests.test_customers import create as create_customer
from tests.test_inventory import adjust
from tests.test_orders import create as create_order, payload as order_payload
from tests.test_products import create as create_product
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def test_postgres_create_update_and_audit_commit_with_tenant_actor(team_client):
    headers, registration = owner(team_client)
    customer = create_customer(team_client, headers, "PG Order Audit Customer")
    product = create_product(team_client, headers, sku="PG-ORDER-AUD", barcode="PG-ORDER-AUD")
    order = create_order(
        team_client, headers, customer["id"], product["id"], order_number="SO-PG-AUDIT-1"
    )
    response = team_client.patch(
        f"/api/v1/orders/{order['id']}",
        headers=headers,
        json=order_payload(customer["id"], product["id"], order_number="SO-PG-AUDIT-2"),
    )
    assert response.status_code == 200

    rows = audits(team_client, registration["business"]["id"], "order")
    assert [row.action for row in rows] == ["order.created", "order.updated"]
    assert rows[1].changed_fields == ["order_number"]
    assert all(row.business_id == UUID(registration["business"]["id"]) for row in rows)
    assert all(row.actor_user_id == UUID(registration["user"]["id"]) for row in rows)
    with pytest.raises(IntegrityError, match="append-only"):
        with team_client.test_engine.begin() as connection:
            connection.execute(
                text("UPDATE audit_logs SET entity_display='changed' WHERE id=:id"),
                {"id": rows[0].id},
            )


def test_postgres_multi_item_confirmation_commits_one_order_audit_and_zero_inventory_audits(team_client):
    headers, registration = owner(team_client)
    order, first, second = create_two_item_order(team_client, headers, "SO-PG-MULTI")
    inventory_baseline = len(audits(team_client, registration["business"]["id"], "inventory"))
    assert team_client.post(f"/api/v1/orders/{order['id']}/confirm", headers=headers).status_code == 200

    status, quantities, movements = order_state(
        team_client, order["id"], [first["id"], second["id"]]
    )
    assert status == "confirmed"
    assert quantities == {first["id"]: Decimal("3"), second["id"]: Decimal("3")}
    assert sum(movement.reason == f"Order {order['order_number']} confirmed" for movement in movements) == 2
    rows = audits(team_client, registration["business"]["id"], "order")
    assert sum(row.action == "order.confirmed" for row in rows) == 1
    assert len(audits(team_client, registration["business"]["id"], "inventory")) == inventory_baseline


@pytest.mark.parametrize("failure", ["audit", "commit"])
def test_postgres_confirmation_failure_rolls_back_order_inventory_movement_and_audit(
    team_client, monkeypatch, failure: str
):
    headers, registration = owner(team_client)
    order, first, second = create_two_item_order(
        team_client, headers, f"SO-PG-{failure.upper()}-FAIL"
    )
    context = context_for(team_client, registration["business"]["id"])
    baseline = len(audits(team_client, registration["business"]["id"], "order"))
    session = Session(team_client.test_engine)
    if failure == "audit":
        def fail_record(self: AuditService, **_: object) -> AuditLog:
            raise AuditPersistenceError("forced audit failure")
        monkeypatch.setattr(AuditService, "record", fail_record)
        expected_error = AuditPersistenceError
    else:
        monkeypatch.setattr(
            session,
            "commit",
            lambda: (_ for _ in ()).throw(RuntimeError("forced commit failure")),
        )
        expected_error = RuntimeError
    try:
        with pytest.raises(expected_error):
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


def test_postgres_insufficient_stock_multi_item_confirmation_is_all_or_nothing(team_client):
    headers, registration = owner(team_client)
    order, first, second = create_two_item_order(
        team_client, headers, "SO-PG-INSUFFICIENT", first_stock="5", second_stock="1"
    )
    order_baseline = len(audits(team_client, registration["business"]["id"], "order"))
    inventory_baseline = len(audits(team_client, registration["business"]["id"], "inventory"))
    response = team_client.post(f"/api/v1/orders/{order['id']}/confirm", headers=headers)
    assert response.status_code == 409

    status, quantities, movements = order_state(
        team_client, order["id"], [first["id"], second["id"]]
    )
    assert status == "draft"
    assert quantities == {first["id"]: Decimal("5"), second["id"]: Decimal("1")}
    assert all(movement.reason != f"Order {order['order_number']} confirmed" for movement in movements)
    assert len(audits(team_client, registration["business"]["id"], "order")) == order_baseline
    assert len(audits(team_client, registration["business"]["id"], "inventory")) == inventory_baseline

