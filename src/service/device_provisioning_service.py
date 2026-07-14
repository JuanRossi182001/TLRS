from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device import (
    Device,
    DeviceCommunicationProtocol,
    DeviceState,
)


class DeviceProvisioningService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def provision_device(
        self,
        serial: str,
        name: str,
        type: str,
        client_id: int | None = None,
        asset_id: int | None = None,
        communication_protocol: DeviceCommunicationProtocol = DeviceCommunicationProtocol.CHIRPSTACK,
        chirpstack_dev_eui: str | None = None,
        chirpstack_application_id: str | None = None,
        lorawan_class: str | None = None,
        chirpstack_device_profile_id: str | None = None,
    ) -> dict:
        if communication_protocol != DeviceCommunicationProtocol.CHIRPSTACK:
            raise ValueError("Only CHIRPSTACK device provisioning is supported")

        if not chirpstack_dev_eui:
            raise ValueError("chirpstack_dev_eui is required for CHIRPSTACK devices")
        device = Device(
            serial=serial,
            name=name,
            type=type,
            state=DeviceState.OFF,
            communication_protocol=DeviceCommunicationProtocol.CHIRPSTACK,
            client_id=client_id,
            asset_id=asset_id,
            active=True,
            chirpstack_dev_eui=chirpstack_dev_eui,
            chirpstack_application_id=chirpstack_application_id,
            lorawan_class=lorawan_class,
            chirpstack_device_profile_id=chirpstack_device_profile_id,
        )

        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)

        return {
            "device": {
                "id_device": device.id_device,
                "serial": device.serial,
                "name": device.name,
                "type": device.type,
                "communication_protocol": device.communication_protocol.value,
                "active": device.active,
                "chirpstack_dev_eui": device.chirpstack_dev_eui,
                "chirpstack_application_id": device.chirpstack_application_id,
                "lorawan_class": device.lorawan_class,
                "chirpstack_device_profile_id": device.chirpstack_device_profile_id,
            },
        }
