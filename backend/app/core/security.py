import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: UUID, business_id: UUID, auth_version: int = 0) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "business_id": str(business_id), "type": "access", "iat": now, "version": auth_version,
         "exp": now + timedelta(minutes=settings.access_token_expire_minutes)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, str]:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "access" or not payload.get("sub") or not payload.get("business_id"):
        raise jwt.InvalidTokenError("Invalid access token")
    return payload


def create_refresh_secret() -> str:
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
