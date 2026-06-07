from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device_command import DeviceCommand, DeviceCommandStatus
from src.schemas.device_command_ack import (
    DeviceCommandAckPayload,
    DeviceCommandAckStatus,
)


@dataclass(slots=True)
class DeviceCommandAckResult:
    success: bool
    command: DeviceCommand | None = None
    failure_reason: str | None = None


class DeviceCommandAckService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def process_ack(
        self,
        payload: DeviceCommandAckPayload,
    ) -> DeviceCommandAckResult:
        command = await self._get_command_by_uuid(payload.command_id)
        if command is None:
            return DeviceCommandAckResult(
                success=False,
                failure_reason="COMMAND_NOT_FOUND",
            )

        now = datetime.utcnow()

        if payload.status in {
            DeviceCommandAckStatus.EXECUTED,
            DeviceCommandAckStatus.DUPLICATE,
        }:
            command.status = DeviceCommandStatus.ACKED
            command.ack_at = self._normalize_datetime(payload.executed_at) or now
            command.failed_at = None
            command.error_message = None

        elif payload.status == DeviceCommandAckStatus.EXPIRED:
            command.status = DeviceCommandStatus.EXPIRED
            command.error_message = (
                payload.error_message or "Device reported command expired"
            )

        elif payload.status in {
            DeviceCommandAckStatus.REJECTED,
            DeviceCommandAckStatus.FAILED,
        }:
            command.status = DeviceCommandStatus.FAILED
            command.failed_at = now
            command.error_message = (
                payload.error_message
                or f"Device reported command {payload.status.value.lower()}"
            )

        self.db.add(command)

        return DeviceCommandAckResult(
            success=True,
            command=command,
        )

    async def _get_command_by_uuid(self, command_uuid: str) -> DeviceCommand | None:
        result = await self.db.execute(
            select(DeviceCommand)
            .where(DeviceCommand.command_uuid == command_uuid)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    def _normalize_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None:
            return value

        return value.astimezone(UTC).replace(tzinfo=None)
