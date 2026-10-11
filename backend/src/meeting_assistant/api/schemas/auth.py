from __future__ import annotations

from pydantic import BaseModel, Field


class UserOut(BaseModel):
    username: str
    created_at: str


class AuthStatus(BaseModel):
    setup_required: bool = Field(description="No account exists yet: the UI shows account creation")
    user: UserOut | None = Field(default=None, description="The signed-in user, if any")


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)
