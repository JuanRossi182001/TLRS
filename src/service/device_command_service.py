from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device import Device
from src.models.device_command import (
    DeviceCommand,
    DeviceCommandStatus,
    DeviceCommandType,
)
from src.models.geofence import FenceEventType, GeoFenceEvent


class DeviceCommandService:
    DEFAULT_QOS = 1
    DEFAULT_RETAIN = False
    DEFAULT_EXPIRES_IN_SECONDS = 300
    NORMAL_REPORT_INTERVAL_SECONDS = 600

    def __init__(self, db: AsyncSession):
        self.db = db

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
            datetime.utcnow() + timedelta(seconds=self.DEFAULT_EXPIRES_IN_SECONDS)
        )
        topic = self._commands_topic(device.serial)
        payload = {
            "command_id": command_uuid,
            "type": command_type.value,
            "reason": reason,
            "expires_at": command_expires_at.isoformat(),
        }
        if payload_fields:
            payload.update(payload_fields)

        command = DeviceCommand(
            command_uuid=command_uuid,
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
            command = await self.create_pending_command(
                device=device,
                command_type=command_type,
                reason=event.event_type.value,
                asset_id=event.asset_id,
                geofence_event_id=event.id_event,
                payload_fields=payload_fields,
            )
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

    def _commands_topic(self, serial: str) -> str:
        return f"gps/devices/{serial}/commands"
