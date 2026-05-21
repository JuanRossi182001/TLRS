from unicodedata import name
from pydantic import BaseModel
from typing import Optional

class ClientBase(BaseModel):
    name: str
    email: str

class ClientCreate(ClientBase):
    pass

class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None

class ClientResponse(BaseModel):
    id_client: int
    name: str
    email: str

class ClientDashboardResponse(BaseModel):
    id_client: int
    name: str
    email: str
    device_count: int
    user_count: int
