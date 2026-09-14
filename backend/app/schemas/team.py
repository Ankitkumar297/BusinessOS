from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RoleAssignment(StrictRequest):
    role_ids: list[UUID] = Field(max_length=50)


class UserCreate(RoleAssignment):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class UserUpdate(StrictRequest):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr


class PermissionAssignment(StrictRequest):
    permission_codes: list[str] = Field(max_length=200)


class RoleWrite(PermissionAssignment):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=255)


class RoleSummary(BaseModel):
    id: UUID
    name: str
    description: str | None
    is_system: bool
    permission_codes: list[str]
    user_count: int


class TeamUser(BaseModel):
    id: UUID
    full_name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    roles: list[RoleSummary]
    permissions: list[str]


class UserPage(BaseModel):
    items: list[TeamUser]
    total: int
    page: int
    page_size: int


class PermissionView(BaseModel):
    code: str
    description: str
    group: str
