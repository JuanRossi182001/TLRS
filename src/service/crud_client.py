from src.models.client import Client
from src.models.device import Device
from src.models.user import User
from sqlalchemy import func, select
from src.schemas.client import (
ClientCreate,
ClientUpdate,
ClientDashboardResponse
)
from src.service.crud_base import CrudBase

class ClientService(CrudBase[Client, ClientCreate, ClientUpdate]):
    model=Client

    async def get_clients_count(self) -> int:
        return await self.db.scalar(select(func.count(Client.id_client)).where(Client.deleted == "N"))

    async def get_clients_dashboard(self, skip: int = 0, limit: int = 20) -> list[ClientDashboardResponse]:
        device_counts = (
            select(
                Device.client_id,
                func.count(Device.id_device).label("device_count"),
            )
            .where(Device.deleted == "N")
            .group_by(Device.client_id)
            .subquery()
        )
        user_counts = (
            select(
                User.id_client,
                func.count(User.id_user).label("user_count"),
            )
            .where(User.deleted == "N")
            .group_by(User.id_client)
            .subquery()
        )
        stmt = (
            select(
                Client.id_client,
                Client.name,
                Client.email,
                func.coalesce(device_counts.c.device_count, 0).label("device_count"),
                func.coalesce(user_counts.c.user_count, 0).label("user_count"),
            )
            .outerjoin(device_counts, Client.id_client == device_counts.c.client_id)
            .outerjoin(user_counts, Client.id_client == user_counts.c.id_client)
            .where(Client.deleted == "N")
            .limit(limit)
            .offset(skip)
        )

        result = await self.db.execute(stmt)
        return result.mappings().all()
