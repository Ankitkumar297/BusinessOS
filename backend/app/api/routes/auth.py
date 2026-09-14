from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import DbSession, TenantContext, get_current_tenant_context
from app.schemas.auth import AuthResponse, LoginRequest, RefreshRequest, RegistrationRequest, UserResponse
from app.services.auth_service import AuthService, user_response

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationRequest, request: Request, db: DbSession) -> AuthResponse:
    return AuthService(db).register(payload, request.headers.get("user-agent"))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> AuthResponse:
    return AuthService(db).login(payload, request.headers.get("user-agent"))


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
