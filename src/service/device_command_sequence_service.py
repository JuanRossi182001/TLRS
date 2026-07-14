from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device_command import DeviceCommand


class DeviceCommandSequenceError(RuntimeError):
    pass


class DeviceCommandSequenceService:
    MIN_COMMAND_SEQ = 1
    MAX_COMMAND_SEQ = 65535
    ADVISORY_LOCK_NAMESPACE = 6101

    def __init__(self, db: AsyncSession):
        self.db = db

    async def allocate_next_command_seq(self, device_id: int) -> int:
        await self._acquire_device_sequence_lock(device_id)
        last_command_seq = await self._get_last_command_seq(device_id)
        pending_last_command_seq = self._get_pending_last_command_seq(device_id)

        if pending_last_command_seq is not None and (
            last_command_seq is None or pending_last_command_seq > last_command_seq
        ):
            last_command_seq = pending_last_command_seq

        if last_command_seq is None:
            return self.MIN_COMMAND_SEQ

        if last_command_seq >= self.MAX_COMMAND_SEQ:
            raise DeviceCommandSequenceError(
                "No command_seq available for device in binary contract v1. "
                "command_seq reuse is not enabled."
            )

        return last_command_seq + 1

    async def _acquire_device_sequence_lock(self, device_id: int) -> None:
        stmt = select(
            func.pg_advisory_xact_lock(
                self.ADVISORY_LOCK_NAMESPACE,
                device_id,
            )
        )
        await self.db.execute(stmt)

    async def _get_last_command_seq(self, device_id: int) -> int | None:
        stmt = select(func.max(DeviceCommand.command_seq)).where(
            DeviceCommand.device_id == device_id,
            DeviceCommand.command_seq.is_not(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    def _get_pending_last_command_seq(self, device_id: int) -> int | None:
        pending_command_seqs = [
            command.command_seq
            for command in self.db.sync_session.new
            if isinstance(command, DeviceCommand)
            and command.device_id == device_id
            and command.command_seq is not None
        ]
        if not pending_command_seqs:
            return None
        return max(pending_command_seqs)
