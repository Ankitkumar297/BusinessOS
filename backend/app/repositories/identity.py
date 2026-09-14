from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Business, Permission, RefreshToken, Role, User
from app.repositories.base import TenantRepository


class BusinessRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, business: Business) -> Business:
        self.db.add(business)
        return business

    def slug_exists(self, slug: str) -> bool:
        return self.db.scalar(select(Business.id).where(Business.slug == slug, Business.deleted_at.is_(None))) is not None


class UserRepository(TenantRepository[User]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, User)

    def add(self, user: User) -> User:
        self.db.add(user)
        return user

    def by_email(self, business_id: UUID, email: str) -> User | None:
        return self.db.scalar(self.tenant_query(business_id).where(User.email == email.lower()).options(selectinload(User.roles).selectinload(Role.permissions)))

    def email_exists(self, email: str) -> bool:
        return self.db.scalar(select(User.id).where(User.email == email.lower(), User.deleted_at.is_(None))) is not None

    def by_id_with_access(self, business_id: UUID, user_id: UUID) -> User | None:
        return self.db.scalar(self.tenant_query(business_id).where(User.id == user_id).options(selectinload(User.roles).selectinload(Role.permissions)))


class RoleRepository(TenantRepository[Role]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, Role)

    def add(self, role: Role) -> Role:
        self.db.add(role)
        return role


class PermissionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def all(self) -> list[Permission]:
        return list(self.db.scalars(select(Permission).where(Permission.deleted_at.is_(None))))

    def add(self, permission: Permission) -> Permission:
        self.db.add(permission)
        return permission


class RefreshTokenRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, token: RefreshToken) -> RefreshToken:
        self.db.add(token)
        return token

    def by_hash(self, token_hash: str) -> RefreshToken | None:
        business_id = self.db.scalar(select(User.business_id).join(RefreshToken, RefreshToken.user_id == User.id)
                                     .where(RefreshToken.token_hash == token_hash))
        if business_id is None:
            return None
        self.db.execute(select(Business.id).where(Business.id == business_id).with_for_update()).one()
        self.db.expire_all()
        return self.db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash, RefreshToken.deleted_at.is_(None)).with_for_update().options(selectinload(RefreshToken.user).selectinload(User.roles).selectinload(Role.permissions)))

    def revoke_all_for_user(self, user_id: UUID, now: datetime) -> None:
        for token in self.db.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))):
            token.revoked_at = now
