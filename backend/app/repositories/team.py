from uuid import UUID
from sqlalchemy import Select, select, func
from sqlalchemy.orm import Session, selectinload
from app.models import Business, Permission, Role, User
from app.models.identity import user_roles


class TeamRepository:
    def __init__(self, db: Session, business_id: UUID) -> None:
        self.db, self.business_id = db, business_id

    def lock_business(self) -> None:
        self.db.execute(select(Business.id).where(Business.id == self.business_id).with_for_update()).one()

    def user_query(self) -> Select[tuple[User]]:
        return select(User).where(User.business_id == self.business_id, User.deleted_at.is_(None))

    def user(self, user_id: UUID) -> User | None:
        return self.db.scalar(self.user_query().where(User.id == user_id).options(selectinload(User.roles).selectinload(Role.permissions)))

    def users(self, search: str, role_id: UUID | None, active: bool | None, page: int, size: int) -> tuple[list[User], int]:
        query = self.user_query()
        if search:
            term = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(User.full_name.ilike(term, escape="\\") | User.email.ilike(term, escape="\\"))
        if role_id:
            query = query.where(User.roles.any(Role.id == role_id))
        if active is not None:
            query = query.where(User.is_active == active)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.scalars(query.options(selectinload(User.roles).selectinload(Role.permissions))
                               .order_by(User.created_at.desc(), User.id).offset((page - 1) * size).limit(size))
        return list(rows), total

    def roles(self) -> list[Role]:
        return list(self.db.scalars(select(Role).where(Role.business_id == self.business_id, Role.deleted_at.is_(None))
                                   .options(selectinload(Role.permissions)).order_by(Role.name)))

    def role(self, role_id: UUID) -> Role | None:
        return self.db.scalar(select(Role).where(Role.business_id == self.business_id, Role.id == role_id,
                              Role.deleted_at.is_(None)).options(selectinload(Role.permissions)))

    def role_count(self, role_id: UUID) -> int:
        return self.db.scalar(select(func.count()).select_from(User).where(User.business_id == self.business_id,
                              User.deleted_at.is_(None), User.roles.any(Role.id == role_id))) or 0

    def role_counts(self) -> dict[UUID, int]:
        rows = self.db.execute(select(user_roles.c.role_id, func.count()).join(User, User.id == user_roles.c.user_id)
                               .where(User.business_id == self.business_id, User.deleted_at.is_(None))
                               .group_by(user_roles.c.role_id))
        return dict(rows.all())

    def owner_count(self) -> int:
        return self.db.scalar(select(func.count()).select_from(User).where(User.business_id == self.business_id,
                              User.deleted_at.is_(None), User.is_active.is_(True),
                              User.roles.any((Role.name == "Owner") & Role.is_system.is_(True) & Role.deleted_at.is_(None)))) or 0

    def permissions(self) -> list[Permission]:
        return list(self.db.scalars(select(Permission).where(Permission.deleted_at.is_(None)).order_by(Permission.code)))
