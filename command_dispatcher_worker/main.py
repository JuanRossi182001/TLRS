import asyncio
import logging
import signal
from datetime import datetime

from sqlalchemy import select

from src.db.config.config import sessionlocal
from src.infrastructure.mqtt.command_publisher import (
    MqttCommandPublisher,
    MqttCommandPublishError,
)
from src.models.device_command import DeviceCommand, DeviceCommandStatus


logger = logging.getLogger("command_dispatcher_worker")
logging.basicConfig(level=logging.INFO)


class CommandDispatcherWorker:
    def __init__(
        self,
        publisher: MqttCommandPublisher,
        batch_limit: int = 50,
        poll_interval_seconds: float = 1.0,
    ):
        self.publisher = publisher
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
                now = datetime.utcnow()
                expired_stmt = (
                    select(DeviceCommand)
                    .where(
                        DeviceCommand.status == DeviceCommandStatus.PENDING,
                        DeviceCommand.expires_at.is_not(None),
                        DeviceCommand.expires_at <= now,
                    )
                    .limit(self.batch_limit)
                    .with_for_update(skip_locked=True)
                )
                expired_result = await db.execute(expired_stmt)
                expired_commands = expired_result.scalars().all()
                for command in expired_commands:
                    command.status = DeviceCommandStatus.EXPIRED
                    db.add(command)

                remaining_limit = self.batch_limit - len(expired_commands)
                if remaining_limit <= 0:
                    await db.commit()
                    return

                pending_stmt = (
                    select(DeviceCommand)
                    .where(
                        DeviceCommand.status == DeviceCommandStatus.PENDING,
                        (
                            (DeviceCommand.expires_at.is_(None))
                            | (DeviceCommand.expires_at > now)
                        ),
                    )
                    .order_by(DeviceCommand.created_at.asc())
                    .limit(remaining_limit)
                    .with_for_update(skip_locked=True)
                )
                pending_result = await db.execute(pending_stmt)
                pending_commands = pending_result.scalars().all()

                for command in pending_commands:
                    await self._publish_command(command)
                    db.add(command)

                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def _publish_command(self, command: DeviceCommand) -> None:
        now = datetime.utcnow()
        try:
            await asyncio.to_thread(
                self.publisher.publish,
                command.topic,
                command.payload,
                command.qos,
                command.retain,
            )
        except MqttCommandPublishError as exc:
            command.status = DeviceCommandStatus.FAILED
            command.failed_at = now
            command.error_message = str(exc)[:500]
            logger.warning(
                "Command publish failed. command_uuid=%s",
                command.command_uuid,
            )
            return

        command.status = DeviceCommandStatus.SENT
        command.sent_at = now
        command.error_message = None
        logger.info("Command sent. command_uuid=%s", command.command_uuid)


async def async_main() -> None:
    publisher = MqttCommandPublisher()
    worker = CommandDispatcherWorker(publisher=publisher)
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)

    await worker.run()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
