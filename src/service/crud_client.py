from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.models.client import Client
from src.models.device import Device
from src.models.user import User
from src.schemas.client import (
    ClientCreate,
    ClientDashboardResponse,
    ClientUpdate,
)
from src.service.crud_base import CrudBase


class ClientEmailConflictError(ValueError):
    """Raised when an active client already uses the requested email."""


class ClientService(CrudBase[Client, ClientCreate, ClientUpdate]):
    model = Client

    async def get_client(self, client_id: int) -> Client | None:
        result = await self.db.execute(
            select(Client).where(
                Client.id_client == client_id,
                Client.deleted == "N",
            )
        )
        return result.scalar_one_or_none()

    async def create_client(self, payload: ClientCreate) -> Client:
        if await self._email_in_use(payload.email):
            raise ClientEmailConflictError("A client with this email already exists.")

        client = Client(name=payload.name, email=payload.email)
        self.db.add(client)
        try:
            await self.db.commit()
            await self.db.refresh(client)
        except IntegrityError as exc:
            await self.db.rollback()
            raise ClientEmailConflictError(
                "A client with this email already exists."
            ) from exc
        return client

    async def update_client(
        self,
        client_id: int,
        payload: ClientUpdate,
    ) -> Client | None:
        client = await self.get_client(client_id)
        if client is None:
            return None

        changes = payload.model_dump(exclude_unset=True)
        email = changes.get("email")
        if email is not None and await self._email_in_use(
            email,
            excluding_client_id=client_id,
        ):
            raise ClientEmailConflictError("A client with this email already exists.")

        for field, value in changes.items():
            setattr(client, field, value)
        self.db.add(client)
        try:
            await self.db.commit()
            await self.db.refresh(client)
        except IntegrityError as exc:
            await self.db.rollback()
            raise ClientEmailConflictError(
                "A client with this email already exists."
            ) from exc
        return client

    async def delete_client(self, client_id: int) -> Client | None:
        client = await self.get_client(client_id)
        if client is None:
            return None

        client.deleted = "Y"
        self.db.add(client)
        await self.db.commit()
        await self.db.refresh(client)
        return client

    async def _email_in_use(
        self,
        email: str,
        *,
        excluding_client_id: int | None = None,
    ) -> bool:
        stmt = select(Client.id_client).where(
            func.lower(Client.email) == email.lower(),
            Client.deleted == "N",
        )
        if excluding_client_id is not None:
            stmt = stmt.where(Client.id_client != excluding_client_id)
        result = await self.db.execute(stmt.limit(1))
        return result.scalar_one_or_none() is not None

    async def get_clients_count(self) -> int:
        return await self.db.scalar(
            select(func.count(Client.id_client)).where(Client.deleted == "N")
        )

    async def get_clients_dashboard(
        self,
        skip: int = 0,
        limit: int = 20,
    ) -> list[ClientDashboardResponse]:
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
