from sqlalchemy import func, select
from src.models.device import Device, DeviceCredential
from src.models.location import Location
from src.schemas.device import (
    DeviceCreate,
    DeviceCredentialCreate,
    DeviceCredentialUpdate,
    DeviceUpdate,
)
from src.service.crud_base import CrudBase


class DeviceService(CrudBase[Device, DeviceCreate, DeviceUpdate]):
    model = Device

    async def get_devices_by_client_id(self, client_id: int):

        stmt = select(
            Device.id_device,
            Device.serial,
            Device.name,
            Device.type,
            Device.state,
            Device.communication_protocol,
            Device.client_id,
            Device.asset_id,
            Device.active
        ).where(Device.client_id == client_id,
                Device.deleted == "N"
        )
        result = await self.db.execute(stmt)
        return result.mappings().all()

    async def get_latest_locations_by_client_id(self, client_id: int):
        latest_location = (
            select(
                Location.id_location.label("id_location"),
                Location.device_id.label("device_id"),
                Location.latitude.label("latitude"),
                Location.longitude.label("longitude"),
                Location.altitude.label("altitude"),
                Location.accuracy.label("accuracy"),
                Location.device_timestamp.label("device_timestamp"),
                Location.received_at.label("received_at"),
                func.row_number()
                .over(
                    partition_by=Location.device_id,
                    order_by=Location.received_at.desc(),
                )
                .label("row_number"),
            )
            .where(Location.deleted == "N")
            .subquery()
        )

        stmt = (
            select(
                Device.id_device,
                Device.serial,
                Device.name,
                Device.type,
                Device.client_id,
                Device.asset_id,
                Device.active,
                latest_location.c.id_location,
                latest_location.c.latitude,
                latest_location.c.longitude,
                latest_location.c.altitude,
                latest_location.c.accuracy,
                latest_location.c.device_timestamp,
                latest_location.c.received_at,
            )
            .outerjoin(
                latest_location,
                (latest_location.c.device_id == Device.id_device)
                & (latest_location.c.row_number == 1),
            )
            .where(
                Device.client_id == client_id,
                Device.deleted == "N",
            )
        )

        result = await self.db.execute(stmt)
        return result.mappings().all()



class DeviceCredentialService(
    CrudBase[DeviceCredential, DeviceCredentialCreate, DeviceCredentialUpdate]
):
    model = DeviceCredential
