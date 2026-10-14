from urllib.parse import parse_qs, urlparse

import pytest

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.schemas.auth import LoginRequest, RegistrationRequest
from app.services.auth_service import AuthService
from app.services.password_reset_service import PasswordResetService


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, *, ex, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def getdel(self, key):
        return self.values.pop(key, None)

    def delete(self, key):
        self.values.pop(key, None)


class FakeSMTP:
    messages = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def login(self, username, password):
        assert username == "sender@gmail.com"
        assert password == "test-app-password"

    def send_message(self, message):
        self.messages.append(message)


def test_reset_is_single_use_and_revokes_old_password(db, monkeypatch):
    import app.services.password_reset_service as module

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_username", "sender@gmail.com")
    monkeypatch.setattr(settings, "smtp_app_password", "test-app-password")
    monkeypatch.setattr(settings, "public_app_url", "https://example.com")
    redis = FakeRedis()
    monkeypatch.setattr(PasswordResetService, "_redis", lambda self: redis)
    monkeypatch.setattr(module.smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.messages.clear()

    AuthService(db).register(RegistrationRequest(business_name="Example", full_name="Owner",
        email="owner@example.com", password="OldPassword123!"))
    service = PasswordResetService(db)
    service.request("owner@example.com")
    assert len(FakeSMTP.messages) == 1
    link = FakeSMTP.messages[0].get_content().splitlines()[1]
    token = parse_qs(urlparse(link).query)["token"][0]
    service.reset(token, "NewPassword123!")
    with pytest.raises(AppError, match="invalid or expired"):
        service.reset(token, "AnotherPassword123!")
    with pytest.raises(AppError, match="Invalid email or password"):
        AuthService(db).login(LoginRequest(email="owner@example.com", password="OldPassword123!"))
    AuthService(db).login(LoginRequest(email="owner@example.com", password="NewPassword123!"))


def test_unknown_email_gets_generic_response_without_email(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_username", "sender@gmail.com")
    monkeypatch.setattr(settings, "smtp_app_password", "test-app-password")
    monkeypatch.setattr(settings, "public_app_url", "https://example.com")
    monkeypatch.setattr(PasswordResetService, "_redis", lambda self: FakeRedis())
    FakeSMTP.messages.clear()
    PasswordResetService(db).request("missing@example.com")
    assert FakeSMTP.messages == []

