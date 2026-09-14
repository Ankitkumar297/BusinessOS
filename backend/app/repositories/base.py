from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.base import UUIDTimestampSoftDeleteModel

ModelT = TypeVar("ModelT", bound=UUIDTimestampSoftDeleteModel)


class TenantRepository(Generic[ModelT]):
    def __init__(self, db: Session, model: type[ModelT]) -> None:
        self.db = db
        self.model = model

    def tenant_query(self, business_id: UUID) -> Select[tuple[ModelT]]:
        return select(self.model).where(self.model.business_id == business_id, self.model.deleted_at.is_(None))  # type: ignore[attr-defined]

    def get_by_id(self, business_id: UUID, entity_id: UUID) -> ModelT | None:
        return self.db.scalar(self.tenant_query(business_id).where(self.model.id == entity_id))
