"""Validated, tenant-owned audit persistence within the caller transaction."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.models.audit import AuditLog
from app.repositories.audit import AuditRepository
from app.repositories.identity import UserRepository
from app.schemas.audit import (
    AUDIT_ACTION_CHANGED_FIELDS,
    AUDIT_ACTION_ENTITIES,
    AuditLogPage,
    AuditLogView,
)
from app.services.auth_service import permissions_for


class AuditError(RuntimeError):
    """Base error for an audit operation that must abort its caller."""


class AuditValidationError(AuditError):
    """The requested audit record violates the closed audit contract."""


class AuditPersistenceError(AuditError):
    """Audit persistence failed without changing caller transaction ownership."""


class AuditService:
    def __init__(self, db: Session, tenant: TenantContext) -> None:
        self.db = db
        self.tenant = tenant
        self.repository = AuditRepository(db)

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: UUID,
        entity_display: str | None = None,
        changed_fields: Iterable[str] = (),
    ) -> AuditLog:
        expected_entity = AUDIT_ACTION_ENTITIES.get(action)
        if expected_entity is None:
            raise AuditValidationError("Unsupported audit action.")
        if entity_type != expected_entity:
            raise AuditValidationError("Audit action does not match entity type.")

        normalized_fields = self._changed_fields(action, changed_fields)
        normalized_display = self._entity_display(entity_display)
        actor = UserRepository(self.db).by_id_with_access(
            self.tenant.business_id, self.tenant.user_id
        )
        if actor is None:
            raise AuditValidationError("Audit actor is unavailable in this tenant.")

        audit_log = AuditLog(
            business_id=self.tenant.business_id,
            actor_user_id=self.tenant.user_id,
            actor_name_snapshot=actor.full_name,
            actor_email_snapshot=actor.email,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_display=normalized_display,
            changed_fields=normalized_fields,
        )
        try:
            self.repository.add(audit_log)
            self.db.flush()
        except SQLAlchemyError as exc:
            # The caller still owns rollback/commit of the now-failed transaction.
            raise AuditPersistenceError("Audit record could not be persisted.") from exc
        return audit_log

    def list(
        self,
        *,
        action: str | None,
        entity_type: str | None,
        entity_id: UUID | None,
        actor_user_id: UUID | None,
        start_date: date | None,
        end_date: date | None,
        page: int,
        page_size: int,
    ) -> AuditLogPage:
        actor = UserRepository(self.db).by_id_with_access(
            self.tenant.business_id, self.tenant.user_id
        )
        if actor is None or "audit.view" not in permissions_for(actor):
            from app.core.exceptions import AppError
            raise AppError(403, "You do not have permission to perform this action.")
        start, end = self._date_bounds(start_date, end_date)
        rows, total = self.repository.list(
            self.tenant.business_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            start=start,
            end=end,
            page=page,
            page_size=page_size,
        )
        return AuditLogPage(
            items=[AuditLogView.model_validate(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def _date_bounds(
        start_date: date | None, end_date: date | None
    ) -> tuple[datetime | None, datetime | None]:
        if start_date and end_date and start_date > end_date:
            from app.core.exceptions import AppError
            raise AppError(422, "start must be on or before end.")
        start = datetime.combine(start_date, time.min, tzinfo=UTC) if start_date else None
        end = (
            datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
            if end_date else None
        )
        return start, end

    @staticmethod
    def _changed_fields(action: str, changed_fields: Iterable[str]) -> list[str]:
        try:
            requested = {field for field in changed_fields}
        except TypeError as exc:
            raise AuditValidationError("Changed fields must be an iterable of names.") from exc
        if any(not isinstance(field, str) or not field for field in requested):
            raise AuditValidationError("Changed fields must be non-empty names.")
        allowed = AUDIT_ACTION_CHANGED_FIELDS[action]
        disallowed = requested - allowed
        if disallowed:
            raise AuditValidationError("Changed fields are not allowed for this action.")
        return sorted(requested)

    @staticmethod
    def _entity_display(entity_display: str | None) -> str | None:
        if entity_display is None:
            return None
        normalized = " ".join(entity_display.split())
        if not normalized:
            return None
        if len(normalized) > 255:
            raise AuditValidationError("Entity display must not exceed 255 characters.")
        return normalized
