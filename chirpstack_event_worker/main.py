import asyncio
import json
import logging
import signal
import ssl
from typing import Any

import src.models  # noqa: F401 - registers SQLAlchemy models before mapper configuration
from paho.mqtt.client import CallbackAPIVersion, Client, MQTTMessage
from redis.exceptions import RedisError

from src.db.config.config import sessionlocal
from src.infrastructure.redis.client import close_redis_client
from src.integrations.chirpstack.mqtt_topics import (
    ChirpStackTopicParseError,
    parse_chirpstack_event_topic,
)
from src.integrations.chirpstack.service import ChirpStackEventService
from src.settings import settings


logger = logging.getLogger("chirpstack_event_worker")
logging.basicConfig(level=logging.INFO)


class ChirpStackEventWorker:
    def __init__(self, processing_concurrency: int = 10):
        self.processing_semaphore = asyncio.Semaphore(processing_concurrency)
        self.stop_event = asyncio.Event()
        self.processing_concurrency = processing_concurrency
        self.client = Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id="chirpstack-event-worker",
        )

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._configure_client(loop)

        logger.info("Starting ChirpStack event worker")
        logger.info("MQTT host: %s", settings.chirpstack_event_mqtt_host)
        logger.info("MQTT port: %s", settings.chirpstack_event_mqtt_port)
        logger.info("MQTT topic filter: %s", settings.chirpstack_mqtt_topic_filter)
        logger.info("MQTT TLS: %s", settings.chirpstack_event_mqtt_tls_enabled)
        logger.info("Processing concurrency: %s", self.processing_concurrency)

        self.client.connect(
            host=settings.chirpstack_event_mqtt_host,
            port=settings.chirpstack_event_mqtt_port,
            keepalive=60,
        )
        self.client.loop_start()

        try:
            await self.stop_event.wait()
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            try:
                await close_redis_client()
            except RedisError as exc:
                logger.warning("Failed to close Redis client. error=%s", exc)

    def stop(self) -> None:
        self.stop_event.set()

    def _configure_client(self, loop: asyncio.AbstractEventLoop) -> None:
        username = settings.chirpstack_event_mqtt_username
        password = settings.chirpstack_event_mqtt_password
        if username:
            self.client.username_pw_set(username=username, password=password)

        if settings.chirpstack_event_mqtt_tls_enabled:
            self.client.tls_set(
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            self.client.tls_insecure_set(False)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._build_on_message(loop)

    def _on_connect(
        self,
        client: Client,
        userdata: Any,
        flags: dict,
        reason_code,
        properties=None,
    ) -> None:
        logger.info("Connected to MQTT broker. reason_code=%s", reason_code)
        if getattr(reason_code, "is_failure", False):
            logger.warning("Connection rejected by broker. reason_code=%s", reason_code)
            return

        client.subscribe(settings.chirpstack_mqtt_topic_filter, qos=1)
        logger.info("Subscribed to topic: %s", settings.chirpstack_mqtt_topic_filter)

    def _on_disconnect(
        self,
        client: Client,
        userdata: Any,
        disconnect_flags=None,
        reason_code=None,
        properties=None,
    ) -> None:
        if reason_code is None:
            reason_code = disconnect_flags
        logger.info("Disconnected from MQTT broker. reason_code=%s", reason_code)

    def _build_on_message(self, loop: asyncio.AbstractEventLoop):
        def on_message(client: Client, userdata: Any, message: MQTTMessage) -> None:
            future = asyncio.run_coroutine_threadsafe(self._process_message(message), loop)
            future.add_done_callback(self._log_processing_error)

        return on_message

    def _log_processing_error(self, future) -> None:
        try:
            future.result()
        except Exception as exc:
            logger.exception("ChirpStack message task failed: %s", exc)

    async def _process_message(self, message: MQTTMessage) -> None:
        async with self.processing_semaphore:
            try:
                topic_info = parse_chirpstack_event_topic(message.topic)
            except ChirpStackTopicParseError as exc:
                logger.warning(
                    "Rejected ChirpStack message due to invalid topic. topic=%s reason=%s",
                    message.topic,
                    exc,
                )
                return

            logger.info(
                "ChirpStack message received. topic=%s dev_eui=%s event_type=%s",
                message.topic,
                topic_info.dev_eui,
                topic_info.event_type,
            )

            try:
                raw_payload = message.payload.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning(
                    "Rejected ChirpStack message due to payload decode error. topic=%s",
                    message.topic,
                )
                return

            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                logger.warning(
                    "Rejected ChirpStack message due to invalid JSON. topic=%s dev_eui=%s",
                    message.topic,
                    topic_info.dev_eui,
                )
                return

            if not isinstance(payload, dict):
                logger.warning(
                    "Rejected ChirpStack message because payload is not an object. topic=%s dev_eui=%s",
                    message.topic,
                    topic_info.dev_eui,
                )
                return

            async with sessionlocal() as db:
                try:
                    service = ChirpStackEventService(db)
                    result = await service.handle_event(message.topic, payload)
                    self._log_processed_result(result)
                except Exception as exc:
                    await db.rollback()
                    logger.exception(
                        "Unexpected ChirpStack processing error. topic=%s dev_eui=%s event_type=%s error=%s",
                        message.topic,
                        topic_info.dev_eui,
                        topic_info.event_type,
                        exc,
                    )

    def _log_processed_result(self, result) -> None:
        if not result.success:
            return

        if result.processed_kind == "location":
            client_id = None
            if result.realtime_location_data is not None:
                client_id = result.realtime_location_data.client_id
            logger.info(
                "Location processed. device_id=%s location_id=%s client_id=%s",
                result.device_id,
                result.location_id,
                client_id,
            )
            return

        if result.command_status_changed and result.command_uuid and result.command_status:
            logger.info(
                "Command updated. command_uuid=%s status=%s",
                result.command_uuid,
                result.command_status,
            )


async def async_main() -> None:
    worker = ChirpStackEventWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)
    await worker.run()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
