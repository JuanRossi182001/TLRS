from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.integrations.chirpstack.downlink_client import ChirpStackDownlinkClient
from src.integrations.chirpstack.downlink_encoder import encode_command_downlink
from src.models.device import Device, DeviceCommunicationProtocol
from src.models.device_command import (
    DeviceCommand,
    DeviceCommandStatus,
    DeviceCommandType,
)
from src.models.geofence import FenceEventType, GeoFenceEvent
from src.service.device_command_sequence_service import (
    DeviceCommandSequenceError,
    DeviceCommandSequenceService,
)
from src.settings import settings


logger = logging.getLogger("device_command_service")


class DeviceCommandService:
    DEFAULT_QOS = 1
    DEFAULT_RETAIN = False
    NORMAL_REPORT_INTERVAL_SECONDS = 600

    def __init__(self, db: AsyncSession):
        self.db = db
        self.chirpstack_downlink_client = ChirpStackDownlinkClient()

    async def create_pending_command(
        self,
        device: Device,
        command_type: DeviceCommandType,
        reason: str,
        asset_id: int | None = None,
        geofence_event_id: int | None = None,
        expires_at: datetime | None = None,
        payload_fields: dict[str, Any] | None = None,
    ) -> DeviceCommand:
        command_uuid = str(uuid4())
        command_expires_at = expires_at or (
            self._utcnow() + timedelta(seconds=settings.command_default_expires_seconds)
        )
        command_seq = await self._allocate_command_seq(device)
        topic, payload = self._resolve_command_transport(
            device=device,
            command_uuid=command_uuid,
            command_seq=command_seq,
            command_type=command_type,
            payload_fields=payload_fields,
        )

        if topic is None or payload is None:
            raise ValueError(
                f"Unable to resolve command transport for device {device.id_device}"
            )

        command = DeviceCommand(
            command_uuid=command_uuid,
            command_seq=command_seq,
            device_id=device.id_device,
            asset_id=asset_id,
            geofence_event_id=geofence_event_id,
            command_type=command_type,
            status=DeviceCommandStatus.PENDING,
            topic=topic,
            payload=payload,
            qos=self.DEFAULT_QOS,
            retain=self.DEFAULT_RETAIN,
            expires_at=command_expires_at,
        )
        self.db.add(command)
        return command

    async def create_commands_for_geofence_event(
        self,
        event: GeoFenceEvent,
        device: Device,
    ) -> list[DeviceCommand]:
        command_specs = self._command_specs_for_event_type(event.event_type)
        commands: list[DeviceCommand] = []

        for command_type, payload_fields in command_specs:
            if await self._has_geofence_command(event.id_event, command_type):
                logger.info(
                    "Skipping duplicate geofence command. geofence_event_id=%s command_type=%s",
                    event.id_event,
                    command_type.value,
                )
                continue

            try:
                command = await self.create_pending_command(
                    device=device,
                    command_type=command_type,
                    reason=event.event_type.value,
                    asset_id=event.asset_id,
                    geofence_event_id=event.id_event,
                    payload_fields=payload_fields,
                )
            except ValueError as exc:
                logger.warning(
                    "Failed to create device command for geofence event. geofence_event_id=%s device_id=%s command_type=%s error=%s",
                    event.id_event,
                    device.id_device,
                    command_type.value,
                    exc,
                )
                continue
            commands.append(command)

        return commands

    def _command_specs_for_event_type(
        self,
        event_type: FenceEventType,
    ) -> list[tuple[DeviceCommandType, dict[str, Any]]]:
        if event_type == FenceEventType.NEAR_LIMIT:
            return [
                (
                    DeviceCommandType.SET_REPORT_INTERVAL,
                    {"interval_seconds": 15},
                ),
                (
                    DeviceCommandType.WARNING_SOUND,
                    {"duration_ms": 1500, "intensity": "LOW"},
                ),
            ]

        if event_type == FenceEventType.EXITED:
            return [
                (
                    DeviceCommandType.SET_REPORT_INTERVAL,
                    {"interval_seconds": 5},
                ),
                (
                    DeviceCommandType.WARNING_SOUND,
                    {"duration_ms": 2000, "intensity": "HIGH"},
                ),
            ]

        if event_type == FenceEventType.RETURNED:
            return [
                (DeviceCommandType.STOP_CORRECTION, {}),
                (
                    DeviceCommandType.SET_REPORT_INTERVAL,
                    {"interval_seconds": self.NORMAL_REPORT_INTERVAL_SECONDS},
                ),
            ]

        if event_type == FenceEventType.GPS_UNCERTAIN:
            return [
                (
                    DeviceCommandType.SET_REPORT_INTERVAL,
                    {"interval_seconds": 30},
                ),
            ]

        return []

    def _resolve_command_transport(
        self,
        device: Device,
        command_uuid: str,
        command_seq: int | None,
        command_type: DeviceCommandType,
        payload_fields: dict[str, Any] | None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        if device.communication_protocol != DeviceCommunicationProtocol.CHIRPSTACK:
            raise ValueError(
                f"Device {device.id_device} does not support ChirpStack downlinks"
            )

        if not device.chirpstack_application_id or not device.chirpstack_dev_eui:
            logger.warning(
                "Skipping ChirpStack command because device is missing application_id or dev_eui. device_id=%s",
                device.id_device,
            )
            return None, None

        if command_seq is None:
            raise ValueError(
                f"ChirpStack command for device {device.id_device} requires command_seq"
            )

        encoded_downlink = encode_command_downlink(
            command_uuid=command_uuid,
            command_seq=command_seq,
            command_type=command_type,
            payload_fields=payload_fields,
        )
        topic = self.chirpstack_downlink_client.build_topic(
            application_id=device.chirpstack_application_id,
            dev_eui=device.chirpstack_dev_eui,
        )
        payload = self.chirpstack_downlink_client.build_payload(
            dev_eui=device.chirpstack_dev_eui,
            encoded_downlink=encoded_downlink,
            confirmed=True,
        )
        return topic, payload

    async def _allocate_command_seq(self, device: Device) -> int | None:
        if device.communication_protocol != DeviceCommunicationProtocol.CHIRPSTACK:
            return None

        sequence_service = DeviceCommandSequenceService(self.db)
        try:
            return await sequence_service.allocate_next_command_seq(device.id_device)
        except DeviceCommandSequenceError as exc:
            raise ValueError(str(exc)) from exc

    async def _has_geofence_command(
        self,
        geofence_event_id: int,
        command_type: DeviceCommandType,
    ) -> bool:
        stmt = select(DeviceCommand.id_command).where(
            DeviceCommand.geofence_event_id == geofence_event_id,
            DeviceCommand.command_type == command_type,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    def _utcnow(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
