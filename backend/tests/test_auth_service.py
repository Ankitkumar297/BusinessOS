from app.core.exceptions import AppError
from app.models import Business, User
from app.repositories.identity import UserRepository
from app.schemas.auth import LoginRequest, RegistrationRequest
from app.services.auth_service import AuthService


def registration(name: str, email: str) -> RegistrationRequest:
    return RegistrationRequest(business_name=name, full_name="Business Owner", email=email, password="CorrectHorseBatteryStaple1")


def test_registration_seeds_tenant_roles_and_owner_permissions(db) -> None:
    response = AuthService(db).register(registration("Acme Corp", "owner@acme.example.com"))

    assert response.business.slug == "acme-corp"
    assert response.user.roles == ["Owner"]
    assert {"business.manage", "users.manage", "roles.manage"}.issubset(response.user.permissions)
    assert db.query(Business).count() == 1


def test_refresh_rotates_token_and_logout_revokes_session(db) -> None:
    service = AuthService(db)
    created = service.register(registration("Acme Corp", "owner@acme.example.com"))
    refreshed = service.refresh(created.refresh_token)

    assert refreshed.refresh_token != created.refresh_token
    service.logout(refreshed.refresh_token)
    try:
        service.refresh(refreshed.refresh_token)
    except AppError as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Revoked token must not refresh a session")


def test_tenant_repository_cannot_cross_business_boundary(db) -> None:
    service = AuthService(db)
    first = service.register(registration("Acme Corp", "owner@acme.example.com"))
    second = service.register(registration("Beta Corp", "owner@beta.example.com"))
    second_user = db.query(User).filter(User.email == "owner@beta.example.com").one()

    assert UserRepository(db).get_by_id(first.business.id, second_user.id) is None
    assert UserRepository(db).get_by_id(second.business.id, second_user.id) is not None


def test_duplicate_email_is_rejected_before_creating_a_second_tenant(db) -> None:
    service = AuthService(db)
    service.register(registration("Acme Corp", "owner@acme.example.com"))
    try:
        service.register(registration("Beta Corp", "owner@acme.example.com"))
    except AppError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Duplicate email registration must fail")
