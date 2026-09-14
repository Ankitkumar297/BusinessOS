from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Business
from app.repositories.identity import UserRepository
from app.services.auth_service import permissions_for

bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class TenantContext:
    user_id: UUID
    business_id: UUID
    permissions: frozenset[str]


def get_current_tenant_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)], db: DbSession
) -> TenantContext:
    if not credentials:
        raise AppError(401, "Authentication is required.")
    try:
        claims = decode_access_token(credentials.credentials)
        user_id, business_id = UUID(claims["sub"]), UUID(claims["business_id"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise AppError(401, "Invalid or expired access token.") from None
    user = UserRepository(db).by_id_with_access(business_id, user_id)
    business = db.get(Business, business_id)
    if not user or not user.is_active or claims.get("version", 0) != user.auth_version or not business or not business.is_active or business.deleted_at:
        raise AppError(401, "Account is unavailable.")
    return TenantContext(user_id=user.id, business_id=business_id, permissions=frozenset(permissions_for(user)))


def require_permission(permission: str):
    def guard(context: Annotated[TenantContext, Depends(get_current_tenant_context)]) -> TenantContext:
        if permission not in context.permissions:
            raise AppError(403, "You do not have permission to perform this action.")
        return context
    return guard
