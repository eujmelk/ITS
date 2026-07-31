from __future__ import annotations

from pydantic import BaseModel, Field

from app.enums import Role
from app.schemas.common import ORMModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserBase(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    email: str | None = None
    full_name: str | None = None
    role: Role = Role.VIEWER
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    email: str | None = None
    full_name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserRead(UserBase, ORMModel):
    id: int


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


# Email stays a permissive string rather than EmailStr: it is informational
# here, and a strict validator only blocks imports of legacy staff lists.
__all__ = [
    "PasswordChange",
    "Token",
    "UserCreate",
    "UserRead",
    "UserUpdate",
]
