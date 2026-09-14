"""Tenant-scoped team workflows. Business row locks serialize authorization mutations."""
from datetime import UTC, datetime
from collections.abc import Iterable
from uuid import UUID
from sqlalchemy.orm import Session
from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.core.security import hash_password
from app.models import Permission, Role, User
from app.repositories.team import TeamRepository
from app.repositories.identity import RefreshTokenRepository
from app.schemas.team import RoleWrite, UserCreate, UserUpdate, TeamUser, RoleSummary, UserPage, PermissionView
from app.services.audit_service import AuditService
from app.services.auth_service import permissions_for
from app.services.team_events import TeamEvent, publish_team_event



class TeamService:
    def __init__(self, db: Session, context: TenantContext) -> None:
        self.db, self.context = db, context
        self.repo = TeamRepository(db, context.business_id)
        self._role_counts: dict[UUID, int] | None = None

    def user(self, user_id: UUID) -> User:
        user = self.repo.user(user_id)
        if not user:
            raise AppError(404, "User not found.")
        return user

    def role(self, role_id: UUID) -> Role:
        role = self.repo.role(role_id)
        if not role:
            raise AppError(404, "Role not found.")
        return role

    def begin(self, permission: str) -> User:
        self.repo.lock_business()
        self.db.expire_all()
        actor = self.user(self.context.user_id)
        if not actor.is_active or permission not in permissions_for(actor):
            raise AppError(403, "You do not have permission to perform this action.")
        return actor

    @staticmethod
    def is_owner(user: User) -> bool:
        return any(role.is_system and role.name == "Owner" and not role.deleted_at for role in user.roles)

    def control(self, actor: User, target: User) -> None:
        if not self.is_owner(actor) and (self.is_owner(target) or not permissions_for(target).issubset(permissions_for(actor))):
            raise AppError(403, "You cannot manage a user with higher privileges.")

    def selectable_roles(self, actor: User, ids: list[UUID]) -> list[Role]:
        roles = [self.role(role_id) for role_id in set(ids)]
        for role in roles:
            codes = {p.code for p in role.permissions if not p.deleted_at}
            if not role.is_active or (not self.is_owner(actor) and
                    ((role.is_system and role.name == "Owner") or not codes.issubset(permissions_for(actor)))):
                raise AppError(403, "You cannot assign this role.")
        return roles

    def finish(self, event: str, entity_type: str, entity_id: UUID,
               entity_display: str, changed_fields: Iterable[str]) -> None:
        AuditService(self.db, self.context).record(
            action=event, entity_type=entity_type, entity_id=entity_id,
            entity_display=entity_display, changed_fields=changed_fields,
        )
        self.db.commit()
        publish_team_event(TeamEvent(event, self.context.business_id, self.context.user_id, entity_id))

    def role_view(self, role: Role) -> RoleSummary:
        if self._role_counts is None:
            self._role_counts = self.repo.role_counts()
        return RoleSummary(id=role.id, name=role.name, description=role.description,
                           is_system=role.is_system, permission_codes=sorted(p.code for p in role.permissions if not p.deleted_at),
                           user_count=self._role_counts.get(role.id, 0))

    def user_view(self, user: User) -> TeamUser:
        return TeamUser(id=user.id, full_name=user.full_name, email=user.email, is_active=user.is_active,
                        created_at=user.created_at, updated_at=user.updated_at,
                        roles=[self.role_view(r) for r in user.roles if not r.deleted_at], permissions=sorted(permissions_for(user)))

    def list_users(self, search: str, role_id: UUID | None, active: bool | None, page: int, size: int) -> UserPage:
        rows, total = self.repo.users(search, role_id, active, page, size)
        return UserPage(items=[self.user_view(u) for u in rows], total=total, page=page, page_size=size)

    def create_user(self, payload: UserCreate) -> TeamUser:
        actor = self.begin("users.create")
        if payload.role_ids and "users.assign_roles" not in permissions_for(actor):
            raise AppError(403, "Role assignment permission is required.")
        user = User(business_id=self.context.business_id, full_name=payload.full_name,
                    email=str(payload.email).lower(), password_hash=hash_password(payload.password),
                    roles=self.selectable_roles(actor, payload.role_ids))
        self.db.add(user)
        self.db.flush()
        result = self.user_view(user)
        self.finish("user.created", "user", user.id, user.full_name,
                    ("full_name", "email", "roles"))
        return result

    def update_user(self, user_id: UUID, payload: UserUpdate) -> TeamUser:
        actor = self.begin("users.update")
        user = self.user(user_id)
        self.control(actor, user)
        next_values = {"full_name": payload.full_name, "email": str(payload.email).lower()}
        changed_fields = [field for field, value in next_values.items() if getattr(user, field) != value]
        user.full_name, user.email = next_values["full_name"], next_values["email"]
        self.db.flush()
        result = self.user_view(user)
        self.finish("user.updated", "user", user.id, user.full_name, changed_fields)
        return result

    def status(self, user_id: UUID, active: bool, delete: bool = False) -> TeamUser:
        actor = self.begin("users.delete" if delete else "users.deactivate")
        user = self.user(user_id)
        self.control(actor, user)
        if user.id == actor.id:
            raise AppError(409, "You cannot deactivate or delete your own account.")
        if not active and self.is_owner(user) and user.is_active and self.repo.owner_count() <= 1:
            raise AppError(409, "The business must retain an active Owner.")
        user.is_active = active
        if delete:
            user.deleted_at = datetime.now(UTC)
        if not active:
            user.auth_version += 1
            RefreshTokenRepository(self.db).revoke_all_for_user(user.id, datetime.now(UTC))
        self.db.flush()
        result = self.user_view(user)
        self.finish("user.deleted" if delete else ("user.activated" if active else "user.deactivated"),
                    "user", user.id, user.full_name, ("is_active",))
        return result

    def assign_roles(self, user_id: UUID, ids: list[UUID]) -> TeamUser:
        actor = self.begin("users.assign_roles")
        user = self.user(user_id)
        self.control(actor, user)
        if user.id == actor.id:
            raise AppError(409, "Ask another authorized user to change your roles.")
        roles = self.selectable_roles(actor, ids)
        keeps_owner = any(r.is_system and r.name == "Owner" for r in roles)
        if self.is_owner(user) and user.is_active and not keeps_owner and self.repo.owner_count() <= 1:
            raise AppError(409, "The business must retain an active Owner.")
        user.roles = roles
        self.db.flush()
        result = self.user_view(user)
        self.finish("user.roles_changed", "user", user.id, user.full_name, ("roles",))
        return result

    def permission_records(self, actor: User, codes: list[str]) -> list[Permission]:
        requested = set(codes)
        available = {p.code: p for p in self.repo.permissions()}
        if requested - available.keys():
            raise AppError(422, "Unknown permission code.")
        if not requested.issubset(permissions_for(actor)):
            raise AppError(403, "You cannot grant permissions you do not hold.")
        return [available[c] for c in sorted(requested)]

    def write_role(self, payload: RoleWrite, role_id: UUID | None = None) -> RoleSummary:
        actor = self.begin("roles.update" if role_id else "roles.create")
        if "roles.assign_permissions" not in permissions_for(actor):
            raise AppError(403, "Permission assignment access is required.")
        role = self.role(role_id) if role_id else Role(business_id=self.context.business_id, is_system=False)
        if role.is_system:
            raise AppError(409, "Default system roles cannot be modified.")
        if role_id:
            self.editable_role(actor, role)
        if payload.name.casefold() in {"owner", "admin", "manager", "employee"}:
            raise AppError(409, "This name is reserved for a system role.")
        permissions = self.permission_records(actor, payload.permission_codes)
        if role_id:
            changed_fields = [
                field for field, changed in (
                    ("name", role.name != payload.name),
                    ("description", role.description != payload.description),
                    ("permissions", {p.code for p in role.permissions} != {p.code for p in permissions}),
                ) if changed
            ]
        else:
            changed_fields = ["name", "description", "permissions"]
        role.name, role.description = payload.name, payload.description
        role.permissions = permissions
        self.db.add(role)
        self.db.flush()
        result = self.role_view(role)
        self.finish("role.updated" if role_id else "role.created", "role", role.id,
                    role.name, changed_fields)
        return result

    def editable_role(self, actor: User, role: Role) -> None:
        if role.is_system:
            raise AppError(409, "Default system roles cannot be modified.")
        if not {p.code for p in role.permissions}.issubset(permissions_for(actor)):
            raise AppError(403, "You cannot manage a role with higher privileges.")
        if any(r.id == role.id for r in actor.roles):
            raise AppError(409, "You cannot modify a role assigned to yourself.")

    def assign_permissions(self, role_id: UUID, codes: list[str]) -> RoleSummary:
        actor = self.begin("roles.assign_permissions")
        role = self.role(role_id)
        self.editable_role(actor, role)
        role.permissions = self.permission_records(actor, codes)
        self.db.flush()
        result = self.role_view(role)
        self.finish("role.permissions_changed", "role", role.id, role.name, ("permissions",))
        return result

    def delete_role(self, role_id: UUID) -> None:
        actor = self.begin("roles.delete")
        role = self.role(role_id)
        self.editable_role(actor, role)
        if self.repo.role_count(role.id):
            raise AppError(409, "Remove this role from its users before deleting it.")
        role.deleted_at = datetime.now(UTC)
        role.is_active = False
        self.db.flush()
        self.finish("role.deleted", "role", role.id, role.name, ("is_active",))

    def permissions(self) -> list[PermissionView]:
        return [PermissionView(code=p.code, description=p.description, group=p.code.split(".")[0]) for p in self.repo.permissions()]
