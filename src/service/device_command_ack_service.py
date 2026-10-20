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
    previous_status: DeviceCommandStatus | None = None


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

        return self._apply_ack_to_command(command, payload)

    async def process_ack_by_command_seq(
        self,
        device_id: int,
        payload: DeviceCommandAckPayload,
    ) -> DeviceCommandAckResult:
        command_seq = payload.command_seq
        if command_seq is None:
            return DeviceCommandAckResult(
                success=False,
                failure_reason="COMMAND_ACK_INVALID_COMMAND_SEQ",
            )

        command = await self._get_command_by_device_and_seq(device_id, command_seq)
        if command is None:
            return DeviceCommandAckResult(
                success=False,
                failure_reason="COMMAND_ACK_COMMAND_SEQ_NOT_FOUND",
            )

        return self._apply_ack_to_command(command, payload)

    def _apply_ack_to_command(
        self,
        command: DeviceCommand,
        payload: DeviceCommandAckPayload,
    ) -> DeviceCommandAckResult:
        previous_status = command.status
        now = datetime.now(UTC).replace(tzinfo=None)

        if payload.status in {
            DeviceCommandAckStatus.EXECUTED,
            DeviceCommandAckStatus.DUPLICATE,
        }:
            command.status = DeviceCommandStatus.ACKED
            command.ack_at = self._normalize_datetime(payload.executed_at) or now
            command.failed_at = None
            command.error_message = payload.error_message

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
            previous_status=previous_status,
        )

    async def _get_command_by_uuid(self, command_uuid: str | None) -> DeviceCommand | None:
        if not command_uuid:
            return None
        result = await self.db.execute(
            select(DeviceCommand)
            .where(DeviceCommand.command_uuid == command_uuid)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _get_command_by_device_and_seq(
        self,
        device_id: int,
        command_seq: int,
    ) -> DeviceCommand | None:
        result = await self.db.execute(
            select(DeviceCommand)
            .where(
                DeviceCommand.device_id == device_id,
                DeviceCommand.command_seq == command_seq,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    def _normalize_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None:
            return value

        return value.astimezone(UTC).replace(tzinfo=None)
