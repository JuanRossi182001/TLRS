import asyncio
import logging
import signal
from datetime import UTC, datetime

from sqlalchemy import select

from src.db.config.config import sessionlocal
from src.infrastructure.downlink import DownlinkTransport, build_downlink_transport
from src.models.device_command import DeviceCommand, DeviceCommandStatus


logger = logging.getLogger("command_dispatcher_worker")
logging.basicConfig(level=logging.INFO)


class CommandDispatcherWorker:
    TERMINAL_STATUSES = (
        DeviceCommandStatus.ACKED,
        DeviceCommandStatus.FAILED,
        DeviceCommandStatus.EXPIRED,
    )

    def __init__(
        self,
        transport: DownlinkTransport,
        batch_limit: int = 50,
        poll_interval_seconds: float = 1.0,
    ):
        self.transport = transport
        self.batch_limit = batch_limit
        self.poll_interval_seconds = poll_interval_seconds
        self._stop = asyncio.Event()

    async def run(self) -> None:
        logger.info("Starting command dispatcher worker")
        while not self._stop.is_set():
            try:
                await self.process_once()
            except Exception as exc:
                logger.exception("Unexpected dispatcher cycle error: %s", exc)

            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()

    async def process_once(self) -> None:
        async with sessionlocal() as db:
            try:
                now = datetime.now(UTC).replace(tzinfo=None)
                expired_stmt = (
                    select(DeviceCommand)
                    .where(
                        DeviceCommand.status.notin_(self.TERMINAL_STATUSES),
                        DeviceCommand.expires_at.is_not(None),
                        DeviceCommand.expires_at <= now,
                    )
                    .order_by(DeviceCommand.created_at.asc())
                    .limit(self.batch_limit)
                    .with_for_update(skip_locked=True)
                )
                expired_result = await db.execute(expired_stmt)
                expired_commands = expired_result.scalars().all()
                for command in expired_commands:
                    command.status = DeviceCommandStatus.EXPIRED
                    command.failed_at = now
                    command.error_message = "Command expired before application ACK"
                    db.add(command)

                if expired_commands:
                    logger.info(
                        "Expired commands. total=%s command_ids=%s",
                        len(expired_commands),
                        [command.id_command for command in expired_commands],
                    )
                    await db.commit()

                remaining_limit = self.batch_limit - len(expired_commands)
                if remaining_limit <= 0:
                    return

                for _ in range(remaining_limit):
                    pending_now = datetime.now(UTC).replace(tzinfo=None)
                    pending_stmt = (
                        select(DeviceCommand)
                        .where(
                            DeviceCommand.status == DeviceCommandStatus.PENDING,
                            (
                                (DeviceCommand.expires_at.is_(None))
                                | (DeviceCommand.expires_at > pending_now)
                            ),
                        )
                        .order_by(DeviceCommand.created_at.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    pending_result = await db.execute(pending_stmt)
                    command = pending_result.scalars().first()
                    if command is None:
                        break

                    await self._enqueue_command(command)
                    db.add(command)
                    await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def _enqueue_command(self, command: DeviceCommand) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        result = await asyncio.to_thread(self.transport.enqueue, command)

        if not result.sent:
            command.error_message = (result.error_message or "Command enqueue failed")[:500]
            if result.retryable:
                logger.warning(
                    "Command enqueue failed and will be retried. command_uuid=%s transport=%s error=%s",
                    command.command_uuid,
                    result.transport,
                    command.error_message,
                )
                return

            command.status = DeviceCommandStatus.FAILED
            command.failed_at = now
            logger.warning(
                "Command enqueue failed. command_uuid=%s transport=%s",
                command.command_uuid,
                result.transport,
            )
            return

        if result.queue_item_id:
            command.chirpstack_queue_item_id = result.queue_item_id
        command.status = DeviceCommandStatus.SENT
        command.sent_at = now
        command.failed_at = None
        command.error_message = None
        logger.info(
            "Command sent. command_uuid=%s transport=%s queue_item_id=%s",
            command.command_uuid,
            result.transport,
            result.queue_item_id,
        )


async def async_main() -> None:
    transport = build_downlink_transport()
    worker = CommandDispatcherWorker(transport=transport)
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)

    await worker.run()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
