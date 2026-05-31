import json

from sqlalchemy import func, select
from src.models.device import Device, DeviceCredential, DeviceState
from src.models.client import Client
from src.models.asset import Asset
from src.models.location import Location
from src.schemas.device import (
    DeviceCreate,
    DeviceCredentialCreate,
    DeviceCredentialUpdate,
    DeviceUpdate,
    DevicesStatsAdminResult
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
                func.ST_AsGeoJSON(Location.point).label("point"),
                Location.device_timestamp.label("device_timestamp"),
                Location.received_at.label("received_at"),
                func.row_number()
                .over(
                    partition_by=Location.device_id,
                    order_by=Location.received_at.desc(),
                )
                .label("row_number"),
            )
            .where(Location.deleted == "N",
                   Location.device_id != None)
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
                latest_location.c.point,
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
                latest_location.c.latitude != None,
                latest_location.c.longitude != None,
                latest_location.c.point != None
            )
        )

        result = await self.db.execute(stmt)
        rows = result.mappings().all()

        return [
            {
                **row,
                "point": json.loads(row["point"]) if row["point"] else None,
            }
            for row in rows
        ]


    async def get_devices_admin_stats(self) -> DevicesStatsAdminResult:
        stmt = (
            select(
                func.count(Device.id_device).label("all_devices"),
                func.count(Device.id_device)
                .filter(Device.active.is_(True))
                .label("active_devices"),
                func.count(Device.id_device)
                .filter(Device.active.is_(False))
                .label("inactive_devices"),
                func.count(Device.id_device)
                .filter(Device.state == DeviceState.ON)
                .label("online_devices"),
                func.count(Device.id_device)
                .filter(Device.state == DeviceState.OFF)
                .label("offline_devices"),
            )
            .where(Device.deleted == "N")
        )
        result = await self.db.execute(stmt)
        stats = result.one()._mapping
        return DevicesStatsAdminResult(
            all_devices=stats["all_devices"],
            active_devices=stats["active_devices"],
            inactive_devices=stats["inactive_devices"],
            online_devices=stats["online_devices"],
            offline_devices=stats["offline_devices"],
        )

    
    async def get_devices(self, skip: int = 0, limit: int = 20):
        stmt = (
            select(
                Device.id_device,
                Device.serial,
                Device.name,
                Client.name.label("client_name"),
                Asset.asset_type.label("asset_name"),
                Device.active,
                Device.state,
            )
            .outerjoin(Client, Device.client_id == Client.id_client)
            .outerjoin(Asset, Device.asset_id == Asset.id_asset)
            .where(Device.deleted == "N")
            .limit(limit)
            .offset(skip)
        )

        result = await self.db.execute(stmt)
        return result.mappings().all()

    async def update_device(self, device_id: int, obj_in: DeviceUpdate) -> Device | None:
        device = await self.get(device_id)
        if device is None:
            return None

        return await self.update(device, obj_in)

    async def deactivate_device(self, device_id: int) -> Device | None:
        device = await self.get(device_id)
        if device is None:
            return None

        device.active = False
        device.state = DeviceState.OFF
        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)
        return device

    async def reactivate_device(self, device_id: int) -> Device | None:
        device = await self.get(device_id)
        if device is None:
            return None

        device.active = True
        device.state = DeviceState.OFF
        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)
        return device


class DeviceCredentialService(
    CrudBase[DeviceCredential, DeviceCredentialCreate, DeviceCredentialUpdate]
):
    model = DeviceCredential
