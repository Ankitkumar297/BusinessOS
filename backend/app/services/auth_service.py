import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.permissions import PERMISSIONS, DEFAULT_ROLES
from app.core.exceptions import AppError
from app.core.security import create_access_token, create_refresh_secret, hash_password, hash_token, verify_password
from app.models import Business, Permission, RefreshToken, Role, User
from app.repositories.identity import BusinessRepository, PermissionRepository, RefreshTokenRepository, RoleRepository, UserRepository
from app.schemas.auth import AuthResponse, BusinessResponse, LoginRequest, RegistrationRequest, UserResponse

def permissions_for(user: User) -> set[str]:
    return {permission.code for role in user.roles if role.is_active and not role.deleted_at
            and role.business_id == user.business_id for permission in role.permissions if not permission.deleted_at}


def user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, full_name=user.full_name, business_id=user.business_id,
                        roles=sorted(role.name for role in user.roles if role.is_active), permissions=sorted(permissions_for(user)))


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.businesses = BusinessRepository(db)
        self.users = UserRepository(db)
        self.roles = RoleRepository(db)
        self.permissions = PermissionRepository(db)
        self.refresh_tokens = RefreshTokenRepository(db)

    def register(self, payload: RegistrationRequest, user_agent: str | None = None) -> AuthResponse:
        if self.users.email_exists(str(payload.email)):
            raise AppError(409, "An account with this email already exists.")
        slug = self._unique_slug(payload.business_name)
        business = self.businesses.add(Business(name=payload.business_name.strip(), slug=slug))
        self.db.flush()
        permission_map = self._ensure_permissions()
        owner_role: Role | None = None
        for role_name, codes in DEFAULT_ROLES.items():
            role = self.roles.add(Role(business_id=business.id, name=role_name, is_system=True,
                                      description=f"Default {role_name} role"))
            role.permissions = [permission_map[code] for code in codes]
            if role_name == "Owner":
                owner_role = role
        user = self.users.add(User(business_id=business.id, email=str(payload.email).lower(),
                                   full_name=payload.full_name.strip(), password_hash=hash_password(payload.password)))
        user.roles = [owner_role] if owner_role else []
        self.db.flush()
        response = self._create_auth_response(user, business, user_agent)
        self.db.commit()
        return response

    def login(self, payload: LoginRequest, user_agent: str | None = None) -> AuthResponse:
        # Email is globally resolved only for login. All post-authentication accesses are tenant scoped.
        user = self.db.scalar(select(User).where(
            User.email == str(payload.email).lower(), User.deleted_at.is_(None)
        ).options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.business)))
        if not user or not user.is_active or not user.business.is_active or user.business.deleted_at or not verify_password(payload.password, user.password_hash):
            raise AppError(401, "Invalid email or password.")
        response = self._create_auth_response(user, user.business, user_agent)
        self.db.commit()
        return response

    def refresh(self, secret: str, user_agent: str | None = None) -> AuthResponse:
        record = self.refresh_tokens.by_hash(hash_token(secret))
        now = datetime.now(UTC)
        expires_at = record.expires_at.replace(tzinfo=UTC) if record and record.expires_at.tzinfo is None else (record.expires_at if record else now)
        if not record or record.revoked_at or expires_at <= now or not record.user.is_active or record.user.deleted_at:
            if record:
                self.refresh_tokens.revoke_all_for_user(record.user_id, now)
                self.db.commit()
            raise AppError(401, "Refresh token is invalid or expired.")
        record.revoked_at = now
        business = self.db.get(Business, record.user.business_id)
        if not business or not business.is_active or business.deleted_at:
            raise AppError(401, "Account is unavailable.")
        response = self._create_auth_response(record.user, business, user_agent)
        self.db.commit()
        return response

    def logout(self, secret: str) -> None:
        record = self.refresh_tokens.by_hash(hash_token(secret))
        if record and not record.revoked_at:
            record.revoked_at = datetime.now(UTC)
            self.db.commit()

    def _create_auth_response(self, user: User, business: Business, user_agent: str | None) -> AuthResponse:
        secret = create_refresh_secret()
        expiry = datetime.now(UTC) + timedelta(days=get_settings().refresh_token_expire_days)
        self.refresh_tokens.add(RefreshToken(user_id=user.id, token_hash=hash_token(secret), expires_at=expiry, user_agent=user_agent))
        return AuthResponse(access_token=create_access_token(user.id, business.id, user.auth_version), refresh_token=secret,
                            user=user_response(user), business=BusinessResponse.model_validate(business))

    def _ensure_permissions(self) -> dict[str, Permission]:
        existing = {permission.code: permission for permission in self.permissions.all()}
        for code, description in PERMISSIONS.items():
            if code not in existing:
                existing[code] = self.permissions.add(Permission(code=code, description=description))
        self.db.flush()
        return existing

    def _unique_slug(self, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:65] or "business"
        candidate, counter = base, 2
        while self.businesses.slug_exists(candidate):
            candidate = f"{base[:70 - len(str(counter))]}-{counter}"
            counter += 1
        return candidate
