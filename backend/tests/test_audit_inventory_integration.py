"""Focused local tests for direct Inventory audit integration."""
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Inventory, StockMovement
from app.schemas.inventory import Adjustment
from app.services import inventory_service as inventory_service_module
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.inventory_service import InventoryService
from tests.test_audit_customer_integration import context_for
from tests.test_customers import create as create_customer
from tests.test_inventory import adjust
from tests.test_orders import create as create_order
from tests.test_products import create as create_product
from tests.test_team import owner, team_client


def inventory_audits(client, business_id: str, inventory_id: str | None = None) -> list[AuditLog]:
    with Session(client.test_engine) as session:
        statement = select(AuditLog).where(
            AuditLog.business_id == UUID(business_id),
            AuditLog.entity_type == "inventory",
        )
        if inventory_id is not None:
            statement = statement.where(AuditLog.entity_id == UUID(inventory_id))
        return list(session.scalars(statement.order_by(AuditLog.created_at, AuditLog.id)))


def persisted_inventory(client, product_id: str) -> tuple[Inventory, list[StockMovement]]:
    with Session(client.test_engine) as session:
        inventory = session.scalar(
            select(Inventory).where(Inventory.product_id == UUID(product_id))
        )
        assert inventory is not None
        session.expunge(inventory)
        movements = list(
            session.scalars(
                select(StockMovement).where(StockMovement.inventory_id == inventory.id)
            )
        )
        for movement in movements:
            session.expunge(movement)
        return inventory, movements


def test_direct_adjustments_create_one_audit_each_without_duplicating_ledger(
    team_client, monkeypatch
):
    headers, registration = owner(team_client)
    product = create_product(
        team_client, headers, "Audited Inventory Product", sku="AUD-INV", barcode="AUD-INV",
        reorder_level="10",
    )
    published = []
    monkeypatch.setattr(inventory_service_module, "publish_team_event", published.append)

    assert adjust(team_client, headers, product["id"], "opening_balance", "20").status_code == 200
    response = adjust(team_client, headers, product["id"], "decrease", "12")
    assert response.status_code == 200
    assert response.json()["quantity_on_hand"] == "8.000"
    inventory_id = response.json()["id"]

    rows = inventory_audits(team_client, registration["business"]["id"], inventory_id)
    assert len(rows) == 2
    assert all(row.action == "inventory.adjusted" for row in rows)
    assert all(row.entity_type == "inventory" for row in rows)
    assert all(row.entity_id == UUID(inventory_id) for row in rows)
    assert all(row.business_id == UUID(registration["business"]["id"]) for row in rows)
    assert all(row.actor_user_id == UUID(registration["user"]["id"]) for row in rows)
    assert all(row.entity_display == "Audited Inventory Product" for row in rows)
    assert all(row.changed_fields == ["quantity_on_hand"] for row in rows)
    assert not hasattr(rows[0], "quantity_before")
    assert not hasattr(rows[0], "quantity_after")
    assert not hasattr(rows[0], "reason")

    inventory, movements = persisted_inventory(team_client, product["id"])
    assert inventory.quantity_on_hand == Decimal("8")
    assert len(movements) == 2
    assert sum(movement.quantity_delta for movement in movements) == Decimal("8")
    assert [event.name for event in published].count("inventory.adjusted") == 2
    assert [event.name for event in published].count("inventory.low_stock") == 1
    assert len(rows) == 2  # The threshold event did not create another AuditLog.


def test_failed_and_cross_tenant_adjustments_create_no_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    product = create_product(
        team_client, first_headers, sku="FAIL-INV", barcode="FAIL-INV",
    )
    assert adjust(team_client, first_headers, product["id"], "opening_balance", "5").status_code == 200
    baseline = len(inventory_audits(team_client, first["business"]["id"]))

    assert adjust(team_client, first_headers, product["id"], "decrease", "6").status_code == 409
    assert adjust(team_client, second_headers, product["id"], "increase", "1").status_code == 404
    assert len(inventory_audits(team_client, first["business"]["id"])) == baseline
    assert inventory_audits(team_client, second["business"]["id"]) == []


def test_forced_audit_failure_rolls_back_inventory_movement_and_audit(team_client, monkeypatch):
    headers, registration = owner(team_client)
    product = create_product(
        team_client, headers, sku="AUD-ROLLBACK", barcode="AUD-ROLLBACK",
    )
    assert adjust(team_client, headers, product["id"], "opening_balance", "10").status_code == 200
    context = context_for(team_client, registration["business"]["id"])

    def fail_record(self: AuditService, **_: object) -> AuditLog:
        raise AuditPersistenceError("forced audit failure")

    monkeypatch.setattr(AuditService, "record", fail_record)
    session = Session(team_client.test_engine)
    try:
        with pytest.raises(AuditPersistenceError, match="forced audit failure"):
            InventoryService(session, context).adjust(
                UUID(product["id"]),
                Adjustment(operation="increase", quantity=Decimal("5"), reason="audit-failure"),
            )
        session.rollback()
    finally:
        session.close()

    inventory, movements = persisted_inventory(team_client, product["id"])
    assert inventory.quantity_on_hand == Decimal("10")
    assert all(movement.reason != "audit-failure" for movement in movements)
    assert len(inventory_audits(team_client, registration["business"]["id"])) == 1


def test_commit_failure_rolls_back_inventory_movement_and_flushed_audit(team_client, monkeypatch):
    headers, registration = owner(team_client)
    product = create_product(
        team_client, headers, sku="COMMIT-ROLLBACK", barcode="COMMIT-ROLLBACK",
    )
    assert adjust(team_client, headers, product["id"], "opening_balance", "10").status_code == 200
    context = context_for(team_client, registration["business"]["id"])
    session = Session(team_client.test_engine)
    monkeypatch.setattr(
        session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("forced commit failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="forced commit failure"):
            InventoryService(session, context).adjust(
                UUID(product["id"]),
                Adjustment(operation="decrease", quantity=Decimal("3"), reason="commit-failure"),
            )
        current = session.scalar(select(Inventory).where(Inventory.product_id == UUID(product["id"])))
        assert current is not None and current.quantity_on_hand == Decimal("7")
        assert session.scalar(
            select(func.count()).select_from(StockMovement).where(StockMovement.reason == "commit-failure")
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.entity_id == current.id,
                AuditLog.action == "inventory.adjusted",
            )
        ) == 2
        session.rollback()
    finally:
        session.close()

    inventory, movements = persisted_inventory(team_client, product["id"])
    assert inventory.quantity_on_hand == Decimal("10")
    assert all(movement.reason != "commit-failure" for movement in movements)
    assert len(inventory_audits(team_client, registration["business"]["id"])) == 1


def test_noncommitting_internal_adjustment_preserves_transaction_ownership_without_audit(team_client):
    headers, registration = owner(team_client)
    product = create_product(
        team_client, headers, sku="INTERNAL-INV", barcode="INTERNAL-INV",
    )
    assert adjust(team_client, headers, product["id"], "opening_balance", "5").status_code == 200
    context = context_for(team_client, registration["business"]["id"])
    with Session(team_client.test_engine) as session:
        result = InventoryService(session, context).adjust(
            UUID(product["id"]),
            Adjustment(operation="decrease", quantity=Decimal("2"), reason="internal-path"),
            commit=False,
            permission=None,
        )
        assert result.quantity_on_hand == Decimal("3")
        session.commit()

    inventory, movements = persisted_inventory(team_client, product["id"])
    assert inventory.quantity_on_hand == Decimal("3")
    assert sum(movement.reason == "internal-path" for movement in movements) == 1
    assert len(inventory_audits(team_client, registration["business"]["id"])) == 1


def test_order_confirmation_uses_internal_adjustment_without_inventory_audit(team_client):
    headers, registration = owner(team_client)
    customer = create_customer(team_client, headers, "Inventory Audit Order Customer")
    product = create_product(
        team_client, headers, sku="ORDER-INV-AUD", barcode="ORDER-INV-AUD",
    )
    assert adjust(team_client, headers, product["id"], "opening_balance", "5").status_code == 200
    order = create_order(team_client, headers, customer["id"], product["id"])
    baseline = len(inventory_audits(team_client, registration["business"]["id"]))

    response = team_client.post(f"/api/v1/orders/{order['id']}/confirm", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "confirmed"
    inventory, movements = persisted_inventory(team_client, product["id"])
    assert inventory.quantity_on_hand == Decimal("3")
    assert sum(movement.reason == f"Order {order['order_number']} confirmed" for movement in movements) == 1
    assert len(inventory_audits(team_client, registration["business"]["id"])) == baseline

