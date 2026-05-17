from sqlalchemy.ext.asyncio import AsyncSession

from src.application.security.credential_generator import CredentialGenerator 
from src.models.device import (
    Device,
    DeviceCommunicationProtocol,
    DeviceState,
    CredentialStatus,
)
from src.models.device import DeviceCredential


class DeviceProvisioningService:
    def __init__(
        self,
        db: AsyncSession,
        credential_generator: CredentialGenerator,
        mqtt_public_host: str,
        mqtt_public_port: int,
        mqtt_tls_enabled: bool,
    ):
        self.db = db
        self.credential_generator = credential_generator
        self.mqtt_public_host = mqtt_public_host
        self.mqtt_public_port = mqtt_public_port
        self.mqtt_tls_enabled = mqtt_tls_enabled

    async def provision_device(
        self,
        serial: str,
        name: str,
        type: str,
        client_id: int | None = None,
        asset_id: int | None = None,
    ) -> dict:
        mqtt_username = self.credential_generator.build_mqtt_username(serial)
        mqtt_password = self.credential_generator.generate_mqtt_password()
        hmac_secret = self.credential_generator.generate_hmac_secret()

        location_topic = f"gps/devices/{serial}/location"
        status_topic = f"gps/devices/{serial}/status"
        heartbeat_topic = f"gps/devices/{serial}/heartbeat"

        device = Device(
            serial=serial,
            name=name,
            type=type,
            state=DeviceState.OFF,
            communication_protocol=DeviceCommunicationProtocol.MQTT,
            client_id=client_id,
            asset_id=asset_id,
            active=True,
        )

        self.db.add(device)
        await self.db.flush()

        credential = DeviceCredential(
            device_id=device.id_device,
            secret=hmac_secret,
            mqtt_username=mqtt_username,
            mqtt_password_encrypted=self.credential_generator.encrypt_password(mqtt_password),
            location_topic=location_topic,
            status_topic=status_topic,
            heartbeat_topic=heartbeat_topic,
            status=CredentialStatus.ACTIVE,
        )

        self.db.add(credential)
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
            },
            "mqtt": {
                "host": self.mqtt_public_host,
                "port": self.mqtt_public_port,
                "tls_enabled": self.mqtt_tls_enabled,
                "username": mqtt_username,
                "password": mqtt_password,
                "location_topic": location_topic,
                "status_topic": status_topic,
                "heartbeat_topic": heartbeat_topic,
            },
            "security": {
                "hmac_secret": hmac_secret,
                "algorithm": "HMAC-SHA256",
            },
        }
