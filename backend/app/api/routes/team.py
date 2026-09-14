from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Response
from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.team import UserCreate, UserUpdate, RoleWrite, RoleAssignment, PermissionAssignment, TeamUser, UserPage, RoleSummary, PermissionView
from app.services.team_service import TeamService

router = APIRouter(tags=["Team"])

@router.get("/users", response_model=UserPage)
def list_users(db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("users.view"))],
               search: str = Query("", max_length=160), role_id: UUID | None = None,
               active: bool | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> UserPage:
    return TeamService(db, ctx).list_users(search, role_id, active, page, page_size)

@router.post("/users", response_model=TeamUser, status_code=201)
def create_user(payload: UserCreate, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("users.create"))]) -> TeamUser:
    return TeamService(db, ctx).create_user(payload)

@router.get("/users/{user_id}", response_model=TeamUser)
def get_user(user_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("users.view"))]) -> TeamUser:
    service = TeamService(db, ctx)
    return service.user_view(service.user(user_id))

@router.patch("/users/{user_id}", response_model=TeamUser)
def update_user(user_id: UUID, payload: UserUpdate, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("users.update"))]) -> TeamUser:
    return TeamService(db, ctx).update_user(user_id, payload)

@router.post("/users/{user_id}/activate", response_model=TeamUser)
def activate_user(user_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("users.deactivate"))]) -> TeamUser:
    return TeamService(db, ctx).status(user_id, True, False)

@router.post("/users/{user_id}/deactivate", response_model=TeamUser)
def deactivate_user(user_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("users.deactivate"))]) -> TeamUser:
    return TeamService(db, ctx).status(user_id, False, False)

@router.delete("/users/{user_id}", response_model=TeamUser)
def delete_user(user_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("users.delete"))]) -> TeamUser:
    return TeamService(db, ctx).status(user_id, False, True)

@router.get("/users/{user_id}/roles", response_model=list[RoleSummary])
def user_roles(user_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("users.view"))]) -> list[RoleSummary]:
    service = TeamService(db, ctx)
    return service.user_view(service.user(user_id)).roles

@router.put("/users/{user_id}/roles", response_model=TeamUser)
def assign_roles(user_id: UUID, payload: RoleAssignment, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("users.assign_roles"))]) -> TeamUser:
    return TeamService(db, ctx).assign_roles(user_id, payload.role_ids)

@router.get("/roles", response_model=list[RoleSummary])
def roles(db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("roles.view"))]) -> list[RoleSummary]:
    service = TeamService(db, ctx)
    return [service.role_view(r) for r in service.repo.roles()]

@router.get("/roles/{role_id}", response_model=RoleSummary)
def role(role_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("roles.view"))]) -> RoleSummary:
    service = TeamService(db, ctx)
    return service.role_view(service.role(role_id))

@router.post("/roles", response_model=RoleSummary, status_code=201)
def create_role(payload: RoleWrite, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("roles.create"))]) -> RoleSummary:
    return TeamService(db, ctx).write_role(payload)

@router.patch("/roles/{role_id}", response_model=RoleSummary)
def update_role(role_id: UUID, payload: RoleWrite, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("roles.update"))]) -> RoleSummary:
    return TeamService(db, ctx).write_role(payload, role_id)

@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("roles.delete"))]) -> Response:
    TeamService(db, ctx).delete_role(role_id)
    return Response(status_code=204)

@router.get("/permissions", response_model=list[PermissionView])
def permissions(db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("roles.view"))]) -> list[PermissionView]:
    return TeamService(db, ctx).permissions()

@router.get("/roles/{role_id}/permissions", response_model=list[str])
def role_permissions(role_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("roles.view"))]) -> list[str]:
    service = TeamService(db, ctx)
    return service.role_view(service.role(role_id)).permission_codes

@router.put("/roles/{role_id}/permissions", response_model=RoleSummary)
def assign_permissions(role_id: UUID, payload: PermissionAssignment, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("roles.assign_permissions"))]) -> RoleSummary:
    return TeamService(db, ctx).assign_permissions(role_id, payload.permission_codes)

