import logging
import secrets
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from urllib.parse import quote
from uuid import UUID

from redis import Redis, RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.security import hash_password, hash_token
from app.models import Business, User
from app.repositories.identity import RefreshTokenRepository

logger = logging.getLogger(__name__)
RESET_TTL_SECONDS = 30 * 60


class PasswordResetService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def _redis(self) -> Redis:
        try:
            return Redis.from_url(self.settings.redis_url, decode_responses=True, socket_timeout=5)
        except ValueError as exc:
            raise AppError(503, "Password reset is temporarily unavailable.") from exc

    def request(self, email: str) -> None:
        if not all((self.settings.smtp_username, self.settings.smtp_app_password, self.settings.public_app_url)):
            raise AppError(503, "Password reset email is not configured yet.")
        normalized = email.lower()
        redis = self._redis()
        throttle_key = f"password-reset:throttle:{hash_token(normalized)}"
        try:
            if not redis.set(throttle_key, "1", ex=60, nx=True):
                return
        except RedisError as exc:
            logger.exception("Password reset Redis unavailable")
            raise AppError(503, "Password reset is temporarily unavailable.") from exc

        user = self.db.scalar(select(User).join(Business).where(
            User.email == normalized, User.deleted_at.is_(None), User.is_active.is_(True),
            Business.deleted_at.is_(None), Business.is_active.is_(True)
        ))
        if user is None:
            return

        token = secrets.token_urlsafe(48)
        token_key = f"password-reset:token:{hash_token(token)}"
        try:
            redis.set(token_key, str(user.id), ex=RESET_TTL_SECONDS)
            link = f"{self.settings.public_app_url.rstrip('/')}/reset-password?token={quote(token)}"
            message = EmailMessage()
            message["From"] = self.settings.smtp_username
            message["To"] = normalized
            message["Subject"] = "Reset your BusinessOS password"
            message.set_content(f"Use this link to reset your password. It expires in 30 minutes:\n{link}\n\nIf you did not request this, ignore this email.")
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
                smtp.login(self.settings.smtp_username, self.settings.smtp_app_password)
                smtp.send_message(message)
        except (RedisError, smtplib.SMTPException, TimeoutError, OSError):
            try:
                redis.delete(token_key)
            except RedisError:
                pass
            logger.exception("Password reset email delivery failed")
            raise AppError(503, "Password reset email could not be sent. Try again later.") from None

    def reset(self, token: str, password: str) -> None:
        redis = self._redis()
        try:
            user_id = redis.getdel(f"password-reset:token:{hash_token(token)}")
        except RedisError as exc:
            logger.exception("Password reset Redis unavailable")
            raise AppError(503, "Password reset is temporarily unavailable.") from exc
        if not user_id:
            raise AppError(400, "Reset link is invalid or expired.")
        user = self.db.scalar(select(User).join(Business).where(
            User.id == UUID(user_id), User.deleted_at.is_(None), User.is_active.is_(True),
            Business.deleted_at.is_(None), Business.is_active.is_(True)
        ).with_for_update())
        if user is None:
            raise AppError(400, "Reset link is invalid or expired.")
        user.password_hash = hash_password(password)
        user.auth_version += 1
        RefreshTokenRepository(self.db).revoke_all_for_user(user.id, datetime.now(UTC))
        self.db.commit()

