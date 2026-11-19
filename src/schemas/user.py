from datetime import datetime
from http import client
from typing import Optional
from pydantic import BaseModel, Field, field_validator

class UserBase(BaseModel):
    id_user: int
    name : str
    email: str 
    hashed_password: str
    id_client: int | None
    is_admin: bool

class UserCreate(BaseModel):
    name : str
    email: str 
    password: str
    id_client: int | None
    is_admin: Optional[bool] = False

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return validate_email(value)


class AdminUserInviteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    id_client: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A name is required.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return validate_email(value)


class EmailActionRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return validate_email(value)


def validate_email(value: str) -> str:
    normalized = value.strip().lower()
    local, separator, domain = normalized.partition("@")
    if (
        not separator
        or not local
        or not domain
        or "." not in domain
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError("A valid email address is required.")
    return normalized


class EmailTokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class PasswordResetRequest(EmailTokenRequest):
    new_password: str = Field(min_length=12, max_length=72)

    @field_validator("new_password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password cannot be longer than 72 bytes.")
        return value


class AccountActionResponse(BaseModel):
    message: str


class UserResponse(BaseModel):
    id_user: int
    name: str
    email: str
    id_client: int | None
    is_admin: bool

    class Config:
        from_attributes = True


class AdminUserInviteResponse(UserResponse):
    invitation_email_sent: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserUpdate(BaseModel):
    name : Optional[str] = None
    email: Optional[str] = None
    id_client: Optional[int] = None
    is_admin: Optional[bool] = None


class TokenData(BaseModel):
    user_id: int
    username: str
    client_id: int | None = None
    is_admin: bool = False
    session_id: int | None = None

class UserDashboardResponse(BaseModel):
    id_user: int
    client_name: str | None = None
    is_admin: bool
    last_login: datetime | None = None
