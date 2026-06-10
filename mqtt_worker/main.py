import asyncio
import json
import signal
import ssl
import sys
import threading
from typing import Any

from paho.mqtt.client import Client, MQTTMessage
from pydantic import ValidationError

from src.settings import settings

from src.application.telemetry.ingress.mqtt_telemetry_ingress import MqttTelemetryIngress
from src.application.telemetry.auth.hmac_device_authenticator import HmacDeviceAuthenticator
from src.application.telemetry.parser.json_telemetry_parser import JsonTelemetryParser
from src.db.config.config import sessionlocal
from src.schemas.device_command_ack import DeviceCommandAckPayload
from src.service.device_command_ack_service import DeviceCommandAckService
from src.service.telemetry_ingestion_service import TelemetryIngestionService


ASYNC_LOOP: asyncio.AbstractEventLoop | None = None
PROCESSING_CONCURRENCY = 10
processing_semaphore: asyncio.Semaphore | None = None
def on_connect(
    client: Client,
    userdata: Any,
    flags: dict,
    reason_code,
    properties=None,
):
    print(f"[MQTT] Connected to broker. Reason code: {reason_code}")

    if int(reason_code) != 0:
        print(f"[MQTT] Connection rejected. Reason code: {reason_code}")
        return

    client.subscribe(settings.mqtt_location_topic, qos=1)
    client.subscribe(settings.mqtt_ack_topic, qos=1)

    print(f"[MQTT] Subscribed to topic: {settings.mqtt_location_topic}")
    print(f"[MQTT] Subscribed to topic: {settings.mqtt_ack_topic}")


def on_disconnect(
    client: Client,
    userdata: Any,
    disconnect_flags=None,
    reason_code=None,
    properties=None,
):
    if reason_code is None:
        reason_code = disconnect_flags

    print(f"[MQTT] Disconnected from broker. Reason code: {reason_code}")


def on_message(client: Client, userdata: Any, message: MQTTMessage):
    if ASYNC_LOOP is None:
        print("[WORKER] Async loop is not running. Message rejected.")
        return

    future = asyncio.run_coroutine_threadsafe(
        process_message_limited(message),
        ASYNC_LOOP,
    )
    future.add_done_callback(log_processing_error)


def log_processing_error(future):
    try:
        future.result()
    except Exception as exc:
        print(f"[WORKER] Message task failed: {exc}")


async def process_message(message: MQTTMessage):
    print("\n[MQTT] Message received")
    print(f"[MQTT] Topic: {message.topic}")

    if message.topic.endswith("/location"):
        await process_location_message(message)
        return

    if message.topic.endswith("/acks"):
        await process_ack_message(message)
        return

    print("[WORKER] Rejected message. Reason: UNSUPPORTED_TOPIC")


async def process_location_message(message: MQTTMessage):
    try:
        raw_payload = message.payload.decode("utf-8")
    except UnicodeDecodeError:
        print("[WORKER] Rejected message. Reason: PAYLOAD_DECODE_ERROR")
        return

    async with sessionlocal() as db:
        try:
            ingress = MqttTelemetryIngress()

            envelope = ingress.build_envelope(
                raw_payload=raw_payload,
                topic=message.topic,
                qos=message.qos,
                retain=message.retain,
                mqtt_client_id=None,
                mqtt_username=settings.mqtt_username,
            )

            print(f"[WORKER] Envelope auth_metadata: {envelope.auth_metadata}")
            print(f"[WORKER] Envelope topic: {envelope.topic}")

            authenticator = HmacDeviceAuthenticator(db=db)
            parser = JsonTelemetryParser()

            ingestion_service = TelemetryIngestionService(
                db=db,
                authenticator=authenticator,
                parser=parser,
            )

            result = await ingestion_service.ingest(envelope)

            if not result.success:
                print(f"[WORKER] Rejected message. Reason: {result.failure_reason}")
                return

            print("[WORKER] Telemetry processed successfully")
            print(f"[WORKER] Device ID: {result.device.id_device if result.device else None}")
            print(f"[WORKER] Location ID: {result.location.id_location if result.location else None}")

        except Exception as exc:
            await db.rollback()
            print(f"[WORKER] Unexpected error: {exc}")


async def process_ack_message(message: MQTTMessage):
    try:
        raw_payload = message.payload.decode("utf-8")
    except UnicodeDecodeError:
        print("[WORKER] ACK rejected. Reason: ACK_PAYLOAD_DECODE_ERROR")
        return

    try:
        payload_data = json.loads(raw_payload)
    except json.JSONDecodeError:
        print("[WORKER] ACK rejected. Reason: ACK_INVALID_JSON")
        return

    if not isinstance(payload_data, dict):
        print("[WORKER] ACK rejected. Reason: ACK_PAYLOAD_NOT_OBJECT")
        return

    try:
        ack_payload = DeviceCommandAckPayload.model_validate(payload_data)
    except ValidationError as exc:
        print(f"[WORKER] ACK rejected. Reason: ACK_VALIDATION_ERROR Detail: {exc}")
        return

    async with sessionlocal() as db:
        try:
            service = DeviceCommandAckService(db)
            result = await service.process_ack(ack_payload)

            if not result.success:
                await db.rollback()
                print(f"[WORKER] ACK rejected. Reason: {result.failure_reason}")
                return

            await db.commit()
            print(f"[WORKER] ACK processed. Command ID: {ack_payload.command_id}")

        except Exception as exc:
            await db.rollback()
            print(f"[WORKER] ACK unexpected error: {exc}")


def shutdown(client: Client):
    print("\n[WORKER] Shutting down...")
    client.loop_stop()
    client.disconnect()
    if ASYNC_LOOP is not None:
        ASYNC_LOOP.call_soon_threadsafe(ASYNC_LOOP.stop)
    sys.exit(0)

async def process_message_limited(message: MQTTMessage):
    if processing_semaphore is None:
        print("[WORKER] Processing semaphore is not initialized. Message rejected.")
        return

    async with processing_semaphore:
        await process_message(message)


def configure_tls(client: Client) -> None:
    if not settings.mqtt_tls_enabled:
        return

    print("[MQTT] TLS enabled")

    client.tls_set(
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )

    client.tls_insecure_set(False)

def start_async_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def init_async_resources():
    global processing_semaphore

    processing_semaphore = asyncio.Semaphore(PROCESSING_CONCURRENCY)

def main():
    global ASYNC_LOOP

    ASYNC_LOOP = asyncio.new_event_loop()

    threading.Thread(
        target=start_async_loop,
        args=(ASYNC_LOOP,),
        daemon=True,
    ).start()

    init_future = asyncio.run_coroutine_threadsafe(
        init_async_resources(),
        ASYNC_LOOP,
    )
    init_future.result(timeout=5)

    client = Client(client_id="gps-mqtt-worker")

    client.username_pw_set(
        username=settings.mqtt_username,
        password=settings.mqtt_password,
    )

    configure_tls(client)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    print("[WORKER] Starting MQTT worker...")
    print(f"[WORKER] MQTT host: {settings.mqtt_host}")
    print(f"[WORKER] MQTT port: {settings.mqtt_port}")
    print(f"[WORKER] MQTT user: {settings.mqtt_username}")
    print(f"[WORKER] MQTT TLS: {settings.mqtt_tls_enabled}")
    print(f"[WORKER] MQTT location topic: {settings.mqtt_location_topic}")
    print(f"[WORKER] MQTT ACK topic: {settings.mqtt_ack_topic}")
    print(f"[WORKER] Processing concurrency: {PROCESSING_CONCURRENCY}")

    client.connect(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        keepalive=60,
    )

    signal.signal(signal.SIGINT, lambda *_: shutdown(client))
    signal.signal(signal.SIGTERM, lambda *_: shutdown(client))

    client.loop_forever()

if __name__ == "__main__":
    main()
