from typing import Optional
from pydantic import BaseModel

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


class UserResponse(BaseModel):
    id_user: int
    name: str
    email: str
    id_client: int | None
    is_admin: bool

    class Config:
        from_attributes = True


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
