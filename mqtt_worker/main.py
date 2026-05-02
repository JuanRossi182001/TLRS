import signal
import sys
from typing import Any

from paho.mqtt.client import Client, MQTTMessage

from mqtt_worker.config import settings

from src.application.telemetry.ingress.mqtt_telemetry_ingress import MqttTelemetryIngress
from src.application.telemetry.auth.hmac_device_authenticator import HmacDeviceAuthenticator
from src.application.telemetry.parser.json_telemetry_parser import JsonTelemetryParser
from src.db.config.config import sessionlocal
from src.service.telemetry_ingestion_service import TelemetryIngestionService


def on_connect(
    client: Client,
    userdata: Any,
    flags: dict,
    reason_code,
    properties=None,
):
    print(f"[MQTT] Connected to broker. Reason code: {reason_code}")

    client.subscribe(settings.mqtt_location_topic, qos=1)

    print(f"[MQTT] Subscribed to topic: {settings.mqtt_location_topic}")


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
    print("\n[MQTT] Message received")
    print(f"[MQTT] Topic: {message.topic}")

    try:
        raw_payload = message.payload.decode("utf-8")
    except UnicodeDecodeError:
        print("[WORKER] Rejected message. Reason: PAYLOAD_DECODE_ERROR")
        return

    db = sessionlocal()

    try:
        ingress = MqttTelemetryIngress()

        
        envelope = ingress.build_envelope(
            raw_payload=raw_payload,
            topic=message.topic,
            qos=message.qos,
            retain=message.retain,
            mqtt_client_id=None,
            mqtt_username=None,
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

        result = ingestion_service.ingest(envelope)

        if not result.success:
            print(f"[WORKER] Rejected message. Reason: {result.failure_reason}")
            return

        print("[WORKER] Telemetry processed successfully")
        print(f"[WORKER] Device ID: {result.device.id_device if result.device else None}")
        print(f"[WORKER] Location ID: {result.location.id_location if result.location else None}")

    except Exception as exc:
        db.rollback()
        print(f"[WORKER] Unexpected error: {exc}")

    finally:
        db.close()


def shutdown(client: Client):
    print("\n[WORKER] Shutting down...")
    client.loop_stop()
    client.disconnect()
    sys.exit(0)


def main():
    client = Client(client_id="gps-mqtt-worker")

    client.username_pw_set(
        username=settings.mqtt_username,
        password=settings.mqtt_password,
    )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    print("[WORKER] Starting MQTT worker...")
    print(f"[WORKER] MQTT host: {settings.mqtt_host}")
    print(f"[WORKER] MQTT port: {settings.mqtt_port}")
    print(f"[WORKER] MQTT user: {settings.mqtt_username}")

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
