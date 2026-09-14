"""Read-only, tenant-scoped audit history API."""
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.audit import AuditAction, AuditEntityType, AuditLogPage
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])
AuditContext = Annotated[TenantContext, Depends(require_permission("audit.view"))]


@router.get("", response_model=AuditLogPage)
def list_audit_logs(
    db: DbSession,
    context: AuditContext,
    action: AuditAction | None = None,
    entity_type: AuditEntityType | None = None,
    entity_id: UUID | None = None,
    actor: UUID | None = None,
    start: date | None = None,
    end: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AuditLogPage:
    return AuditService(db, context).list(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor,
        start_date=start,
        end_date=end,
        page=page,
        page_size=page_size,
    )
