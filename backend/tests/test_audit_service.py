"""Focused local contract tests for the isolated audit core."""
import inspect
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.models import AuditLog, Business, User
from app.repositories.audit import AuditRepository
from app.services.audit_service import (
    AuditPersistenceError,
    AuditService,
    AuditValidationError,
)
from app.services import team_events


def actor_fixture(db: Session) -> tuple[Business, User, TenantContext]:
    business = Business(name="Audit Tenant", slug=f"audit-{uuid4().hex[:8]}")
    db.add(business)
    db.flush()
    actor = User(
        business_id=business.id,
        full_name="Audit Owner",
        email=f"audit-{uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-password-hash",
    )
    db.add(actor)
    db.commit()
    return business, actor, TenantContext(
        user_id=actor.id, business_id=business.id, permissions=frozenset()
    )


def test_records_valid_tenant_actor_snapshot_and_deterministic_fields(db: Session):
    business, actor, tenant = actor_fixture(db)
    entity_id = uuid4()

    record = AuditService(db, tenant).record(
        action="customer.updated",
        entity_type="customer",
        entity_id=entity_id,
        entity_display="  Apex   Customer  ",
        changed_fields=["phone", "email", "phone"],
    )

    assert isinstance(record.id, UUID)
    assert record.business_id == business.id
    assert record.actor_user_id == actor.id
    assert record.actor_name_snapshot == "Audit Owner"
    assert record.actor_email_snapshot == actor.email
    assert record.action == "customer.updated"
    assert record.entity_type == "customer"
    assert record.entity_id == entity_id
    assert record.entity_display == "Apex Customer"
    assert record.changed_fields == ["email", "phone"]
    assert record.created_at is not None
    assert db.scalar(select(AuditLog).where(AuditLog.id == record.id)) is record


@pytest.mark.parametrize(
    ("action", "entity_type", "changed_fields"),
    [
        ("login.succeeded", "user", ()),
        ("customer.updated", "supplier", ()),
        ("customer.updated", "customer", ("password",)),
        ("inventory.low_stock", "inventory", ()),
        ("payment.completed", "payment", ("status",)),
    ],
)
def test_rejects_unsupported_actions_entity_pairs_and_fields(
    db: Session, action: str, entity_type: str, changed_fields: tuple[str, ...]
):
    _, _, tenant = actor_fixture(db)
    with pytest.raises(AuditValidationError):
        AuditService(db, tenant).record(
            action=action,
            entity_type=entity_type,
            entity_id=uuid4(),
            changed_fields=changed_fields,
        )
    assert db.scalar(select(AuditLog)) is None


def test_entity_display_is_optional_normalized_and_bounded(db: Session):
    _, _, tenant = actor_fixture(db)
    blank = AuditService(db, tenant).record(
        action="order.confirmed",
        entity_type="order",
        entity_id=uuid4(),
        entity_display=" \n\t ",
        changed_fields=["status"],
    )
    assert blank.entity_display is None
    db.rollback()

    with pytest.raises(AuditValidationError):
        AuditService(db, tenant).record(
            action="order.confirmed",
            entity_type="order",
            entity_id=uuid4(),
            entity_display="x" * 256,
        )


def test_actor_must_resolve_with_both_tenant_and_user(db: Session):
    business, actor, _ = actor_fixture(db)
    other = Business(name="Other Tenant", slug=f"other-{uuid4().hex[:8]}")
    db.add(other)
    db.commit()

    cross_tenant = TenantContext(
        user_id=actor.id, business_id=other.id, permissions=frozenset()
    )
    missing_actor = TenantContext(
        user_id=uuid4(), business_id=business.id, permissions=frozenset()
    )
    for tenant in (cross_tenant, missing_actor):
        with pytest.raises(AuditValidationError, match="actor"):
            AuditService(db, tenant).record(
                action="customer.created",
                entity_type="customer",
                entity_id=uuid4(),
            )
    assert db.scalar(select(AuditLog)) is None


def test_record_api_cannot_accept_ownership_snapshots_or_payloads(db: Session):
    _, _, tenant = actor_fixture(db)
    parameters = inspect.signature(AuditService.record).parameters
    forbidden = {
        "business_id", "actor_user_id", "actor_name_snapshot",
        "actor_email_snapshot", "metadata", "before", "after",
    }
    assert forbidden.isdisjoint(parameters)

    with pytest.raises(TypeError):
        AuditService(db, tenant).record(
            action="customer.created",
            entity_type="customer",
            entity_id=uuid4(),
            metadata={"password": "secret"},  # type: ignore[call-arg]
        )


def test_record_flushes_without_commit_and_caller_rollback_removes_row(db: Session):
    _, _, tenant = actor_fixture(db)
    record = AuditService(db, tenant).record(
        action="inventory.adjusted",
        entity_type="inventory",
        entity_id=uuid4(),
        changed_fields=["quantity_on_hand"],
    )
    record_id = record.id
    assert db.get(AuditLog, record_id) is not None

    db.rollback()
    with Session(db.get_bind()) as fresh:
        assert fresh.get(AuditLog, record_id) is None


def test_caller_commit_persists_and_service_does_not_publish_event(
    db: Session, monkeypatch: pytest.MonkeyPatch
):
    _, _, tenant = actor_fixture(db)
    published: list[object] = []
    monkeypatch.setattr(team_events, "publish_team_event", published.append)
    record = AuditService(db, tenant).record(
        action="invoice.issued",
        entity_type="invoice",
        entity_id=uuid4(),
        changed_fields=["invoice_number", "grand_total"],
    )
    record_id = record.id
    db.commit()

    with Session(db.get_bind()) as fresh:
        persisted = fresh.get(AuditLog, record_id)
        assert persisted is not None
        assert persisted.changed_fields == ["grand_total", "invoice_number"]
    assert published == []


def test_persistence_error_is_distinct_and_does_not_rollback_caller(
    db: Session, monkeypatch: pytest.MonkeyPatch
):
    _, _, tenant = actor_fixture(db)
    service = AuditService(db, tenant)
    rollbacks: list[bool] = []

    def fail_add(_: AuditLog) -> AuditLog:
        raise IntegrityError("insert audit", {}, RuntimeError("forced failure"))

    monkeypatch.setattr(service.repository, "add", fail_add)
    monkeypatch.setattr(db, "rollback", lambda: rollbacks.append(True))
    with pytest.raises(AuditPersistenceError):
        service.record(
            action="customer.created",
            entity_type="customer",
            entity_id=uuid4(),
        )
    assert rollbacks == []


def test_repository_is_append_only_by_shape():
    assert hasattr(AuditRepository, "add")
    assert not hasattr(AuditRepository, "update")
    assert not hasattr(AuditRepository, "delete")
    assert not hasattr(AuditRepository, "soft_delete")
