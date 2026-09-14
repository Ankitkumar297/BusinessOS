"""Real PostgreSQL atomicity checks for direct Inventory audit integration."""
import os
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, Inventory, StockMovement
from app.schemas.inventory import Adjustment
from app.services.audit_service import AuditPersistenceError, AuditService
from app.services.inventory_service import InventoryService
from tests.test_audit_customer_integration import context_for
from tests.test_customers import create as create_customer
from tests.test_inventory import adjust
from tests.test_orders import create as create_order
from tests.test_products import create as create_product
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def state(client, product_id: str, business_id: str) -> tuple[Decimal, list[StockMovement], list[AuditLog]]:
    with Session(client.test_engine) as session:
        inventory = session.scalar(
            select(Inventory).where(Inventory.product_id == UUID(product_id))
        )
        assert inventory is not None
        movements = list(
            session.scalars(select(StockMovement).where(StockMovement.inventory_id == inventory.id))
        )
        audits = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.business_id == UUID(business_id),
                    AuditLog.entity_id == inventory.id,
                    AuditLog.action == "inventory.adjusted",
                )
            )
        )
        return inventory.quantity_on_hand, movements, audits


def test_postgres_direct_adjustment_commits_ledger_and_one_tenant_safe_audit(team_client):
    headers, registration = owner(team_client)
    product = create_product(team_client, headers, sku="PG-AUD-INV", barcode="PG-AUD-INV")
    response = adjust(team_client, headers, product["id"], "opening_balance", "10")
    assert response.status_code == 200

    quantity, movements, audits = state(
        team_client, product["id"], registration["business"]["id"]
    )
    assert quantity == Decimal("10")
    assert len(movements) == 1
    assert len(audits) == 1
    assert audits[0].business_id == UUID(registration["business"]["id"])
    assert audits[0].actor_user_id == UUID(registration["user"]["id"])
    assert audits[0].changed_fields == ["quantity_on_hand"]

    with pytest.raises(IntegrityError, match="append-only"):
        with team_client.test_engine.begin() as connection:
            connection.execute(
                text("UPDATE audit_logs SET entity_display='changed' WHERE id=:id"),
                {"id": audits[0].id},
            )


def test_postgres_audit_failure_rolls_back_inventory_and_movement(team_client, monkeypatch):
    headers, registration = owner(team_client)
    product = create_product(team_client, headers, sku="PG-AUD-FAIL", barcode="PG-AUD-FAIL")
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
                Adjustment(operation="increase", quantity=Decimal("5"), reason="pg-audit-failure"),
            )
        session.rollback()
    finally:
        session.close()

    quantity, movements, audits = state(
        team_client, product["id"], registration["business"]["id"]
    )
    assert quantity == Decimal("10")
    assert all(movement.reason != "pg-audit-failure" for movement in movements)
    assert len(audits) == 1


def test_postgres_commit_failure_rolls_back_inventory_movement_and_audit(team_client, monkeypatch):
    headers, registration = owner(team_client)
    product = create_product(team_client, headers, sku="PG-COMMIT-FAIL", barcode="PG-COMMIT-FAIL")
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
                Adjustment(operation="decrease", quantity=Decimal("3"), reason="pg-commit-failure"),
            )
        session.rollback()
    finally:
        session.close()

    quantity, movements, audits = state(
        team_client, product["id"], registration["business"]["id"]
    )
    assert quantity == Decimal("10")
    assert all(movement.reason != "pg-commit-failure" for movement in movements)
    assert len(audits) == 1


def test_postgres_cross_tenant_and_order_internal_paths_create_no_inventory_audit(team_client):
    first_headers, first = owner(team_client)
    second_headers, second = owner(team_client, "Other")
    customer = create_customer(team_client, first_headers, "PG Inventory Audit Customer")
    product = create_product(team_client, first_headers, sku="PG-ORDER-AUD", barcode="PG-ORDER-AUD")
    assert adjust(team_client, first_headers, product["id"], "opening_balance", "5").status_code == 200
    order = create_order(team_client, first_headers, customer["id"], product["id"])

    assert adjust(team_client, second_headers, product["id"], "increase", "1").status_code == 404
    assert team_client.post(f"/api/v1/orders/{order['id']}/confirm", headers=first_headers).status_code == 200

    quantity, movements, audits = state(
        team_client, product["id"], first["business"]["id"]
    )
    assert quantity == Decimal("3")
    assert len(movements) == 2
    assert len(audits) == 1
    with Session(team_client.test_engine) as session:
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.business_id == UUID(second["business"]["id"]),
                AuditLog.entity_type == "inventory",
            )
        ) == 0

