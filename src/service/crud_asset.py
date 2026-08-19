from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.asset import Asset
from src.models.client import Client
from src.models.device import Device
from src.schemas.asset import AssetCreate, AssetListItem, AssetUpdate
from src.service.crud_base import CrudBase


class AssetNotFoundError(ValueError):
    pass


class AssetService(CrudBase[Asset, AssetCreate, AssetUpdate]):
    model = Asset

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def create_asset(self, payload: AssetCreate) -> Asset:
        await self._validate_client(payload.client_id)
        return await self.create(payload)

    async def get_assets(
        self,
        *,
        client_id: int,
        unassigned: bool | None = None,
    ) -> list[AssetListItem]:
        await self._validate_client(client_id)
        assigned_device = Device.id_device.label("assigned_device_id")
        stmt = (
            select(
                Asset.id_asset,
                Asset.asset_type,
                Asset.serial,
                Asset.client_id,
                Asset.status,
                assigned_device,
            )
            .outerjoin(
                Device,
                and_(
                    Device.asset_id == Asset.id_asset,
                    Device.deleted == "N",
                ),
            )
            .where(
                Asset.client_id == client_id,
                Asset.deleted == "N",
            )
            .order_by(Asset.id_asset)
        )

        if unassigned is True:
            stmt = stmt.where(Device.id_device.is_(None))
        elif unassigned is False:
            stmt = stmt.where(Device.id_device.is_not(None))

        result = await self.db.execute(stmt)
        return [AssetListItem.model_validate(row) for row in result.mappings().all()]

    async def _validate_client(self, client_id: int) -> None:
        result = await self.db.execute(
            select(Client.id_client).where(
                Client.id_client == client_id,
                Client.deleted == "N",
            )
        )
        if result.scalar_one_or_none() is None:
            raise AssetNotFoundError("Client not found.")
