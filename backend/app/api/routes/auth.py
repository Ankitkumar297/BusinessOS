from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import DbSession, TenantContext, get_current_tenant_context
from app.schemas.auth import AuthResponse, ForgotPasswordRequest, LoginRequest, RefreshRequest, RegistrationRequest, ResetPasswordRequest, UserResponse
from app.services.auth_service import AuthService, user_response
from app.services.password_reset_service import PasswordResetService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationRequest, request: Request, db: DbSession) -> AuthResponse:
    return AuthService(db).register(payload, request.headers.get("user-agent"))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> AuthResponse:
    return AuthService(db).login(payload, request.headers.get("user-agent"))


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> dict[str, str]:
    PasswordResetService(db).request(str(payload.email))
    return {"message": "If this account exists, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: DbSession) -> dict[str, str]:
    PasswordResetService(db).reset(payload.token, payload.password)
    return {"message": "Password updated. Sign in with your new password."}


@router.post("/refresh", response_model=AuthResponse)
def refresh(payload: RefreshRequest, request: Request, db: DbSession) -> AuthResponse:
    return AuthService(db).refresh(payload.refresh_token, request.headers.get("user-agent"))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: DbSession) -> Response:
    AuthService(db).logout(payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
def me(db: DbSession, context: TenantContext = Depends(get_current_tenant_context)) -> UserResponse:
    user = AuthService(db).users.by_id_with_access(context.business_id, context.user_id)
    assert user is not None
    return user_response(user)

