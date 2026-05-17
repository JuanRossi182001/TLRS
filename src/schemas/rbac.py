from pydantic import BaseModel


class RoleCreate(BaseModel):
    name: str


class RoleResponse(BaseModel):
    id_role: int
    name: str
    deleted: str

    class Config:
        from_attributes = True


class ServiceCreate(BaseModel):
    name: str


class ServiceResponse(BaseModel):
    id_service: int
    name: str
    deleted: str

    class Config:
        from_attributes = True


class UserRoleResponse(BaseModel):
    id_user_role: int
    user_id: int
    role_id: int
    deleted: str

    class Config:
        from_attributes = True


class ServiceRoleResponse(BaseModel):
    id_service_role: int
    service_id: int
    role_id: int
    deleted: str

    class Config:
        from_attributes = True
