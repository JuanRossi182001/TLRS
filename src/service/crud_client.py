from src.models.client import Client
from src.schemas.client import (
ClientCreate,
ClientUpdate
)
from src.service.crud_base import CrudBase

class ClientService(CrudBase[Client, ClientCreate, ClientUpdate]):
    model=Client