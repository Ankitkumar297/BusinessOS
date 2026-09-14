"""Minimal append-only persistence for audit records."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


class AuditRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, audit_log: AuditLog) -> AuditLog:
        self.db.add(audit_log)
        return audit_log

    def list(
        self,
        business_id: UUID,
        *,
        action: str | None,
        entity_type: str | None,
        entity_id: UUID | None,
        actor_user_id: UUID | None,
        start: datetime | None,
        end: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditLog], int]:
        query = select(AuditLog).where(AuditLog.business_id == business_id)
        if action is not None:
            query = query.where(AuditLog.action == action)
        if entity_type is not None:
            query = query.where(AuditLog.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(AuditLog.entity_id == entity_id)
        if actor_user_id is not None:
            query = query.where(AuditLog.actor_user_id == actor_user_id)
        if start is not None:
            query = query.where(AuditLog.created_at >= start)
        if end is not None:
            query = query.where(AuditLog.created_at < end)
        total = self.db.scalar(
            select(func.count()).select_from(query.order_by(None).subquery())
        ) or 0
        rows = self.db.scalars(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total
