"""Append-only audit records for authenticated tenant mutations."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """A durable mutation record without update or soft-delete fields."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "actor_user_id"],
            ["users.business_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_audit_logs_actor_tenant",
        ),
        Index("ix_audit_logs_business_created", "business_id", "created_at", "id"),
        Index("ix_audit_logs_business_action_created", "business_id", "action", "created_at"),
        Index(
            "ix_audit_logs_business_entity",
            "business_id",
            "entity_type",
            "entity_id",
            "created_at",
        ),
        Index(
            "ix_audit_logs_business_actor_created",
            "business_id",
            "actor_user_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    actor_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_email_snapshot: Mapped[str] = mapped_column(String(320), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    entity_display: Mapped[str | None] = mapped_column(String(255))
    changed_fields: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
