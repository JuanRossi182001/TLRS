import base64
import json
import os
import ssl
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paho.mqtt.client import CallbackAPIVersion, Client, MQTT_ERR_SUCCESS, MQTTMessage


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.chirpstack.binary_contract import (
    COMMAND_ACK_ERROR_INVALID_PAYLOAD,
    COMMAND_ACK_ERROR_NO_ERROR,
    COMMAND_ACK_FPORT,
    COMMAND_ACK_STATUS_DUPLICATE,
    COMMAND_ACK_STATUS_EXECUTED,
    COMMAND_ACK_STATUS_EXPIRED,
    COMMAND_ACK_STATUS_FAILED,
    COMMAND_ACK_STATUS_REJECTED,
    PROTOCOL_VERSION_V1,
)
from src.integrations.chirpstack.downlink_encoder import decode_command_downlink_payload_v1
from src.integrations.chirpstack.mqtt_topics import (
    ChirpStackTopicParseError,
    parse_chirpstack_downlink_topic,
)
from src.settings import settings


def mqtt_host() -> str:
    return settings.chirpstack_event_mqtt_host


def mqtt_port() -> int:
    return settings.chirpstack_event_mqtt_port


def mqtt_username() -> str | None:
    return settings.chirpstack_event_mqtt_username


def mqtt_password() -> str | None:
    return settings.chirpstack_event_mqtt_password


def mqtt_tls_enabled() -> bool:
    return settings.chirpstack_event_mqtt_tls_enabled


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def simulated_ack_status() -> str:
    return os.getenv("SIMULATE_DEVICE_ACK_STATUS", "EXECUTED").strip().upper()


def simulated_ack_status_code() -> int:
    mapping = {
        "EXECUTED": COMMAND_ACK_STATUS_EXECUTED,
        "REJECTED": COMMAND_ACK_STATUS_REJECTED,
        "FAILED": COMMAND_ACK_STATUS_FAILED,
        "EXPIRED": COMMAND_ACK_STATUS_EXPIRED,
        "DUPLICATE": COMMAND_ACK_STATUS_DUPLICATE,
    }
    return mapping[simulated_ack_status()]


def build_txack_payload(command_uuid: str) -> dict[str, Any]:
    return {
        "commandId": command_uuid,
        "queueItemId": None,
        "gatewayId": "gateway-sim-001",
        "time": now_iso(),
        "status": "OK",
    }


def build_network_ack_payload(command_uuid: str) -> dict[str, Any]:
    return {
        "commandId": command_uuid,
        "queueItemId": None,
        "acknowledged": True,
        "time": now_iso(),
    }


def build_application_ack_payload(
    application_id: str,
    dev_eui: str,
    command_seq: int,
    status_code: int,
    error_code: int,
) -> dict[str, Any]:
    encoded_ack = base64.b64encode(
        struct.pack(
            ">BHBB",
            PROTOCOL_VERSION_V1,
            command_seq,
            status_code,
            error_code,
        )
    ).decode("ascii")
    return {
        "deduplicationId": f"ack-{dev_eui}-{command_seq}-{int(time.time() * 1000)}",
        "time": now_iso(),
        "deviceInfo": {
            "applicationId": application_id,
            "devEui": dev_eui,
        },
        "fPort": COMMAND_ACK_FPORT,
        "data": encoded_ack,
    }


def extract_command_metadata(payload: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    command_id = payload.get("commandId")
    command_seq = payload.get("commandSeq")

    command_uuid = command_id.strip() if isinstance(command_id, str) and command_id.strip() else None
    command_seq_value = command_seq if isinstance(command_seq, int) and command_seq > 0 else None

    data = payload.get("data")
    if not isinstance(data, str) or not data.strip():
        return command_uuid, command_seq_value, None

    try:
        decoded = base64.b64decode(data.encode("ascii"))
        decoded_downlink = decode_command_downlink_payload_v1(decoded)
    except Exception as exc:
        return command_uuid, command_seq_value, str(exc)

    return command_uuid, decoded_downlink.command_seq, None


def publish_json(client: Client, topic: str, payload: dict[str, Any]) -> None:
    print(f"[CHIRPSTACK ACK SIM] Publishing to {topic}")
    print(json.dumps(payload, indent=2))
    result = client.publish(topic=topic, payload=json.dumps(payload), qos=1)
    result.wait_for_publish(timeout=10)
    if result.rc != MQTT_ERR_SUCCESS:
        raise RuntimeError(f"MQTT publish failed with rc={result.rc}")


def on_connect(client: Client, userdata: Any, flags: Any, reason_code: Any, properties=None) -> None:
    print(f"[CHIRPSTACK ACK SIM] Connected. reason_code={reason_code}")
    client.subscribe("application/+/device/+/command/down", qos=1)
    print("[CHIRPSTACK ACK SIM] Subscribed to application/+/device/+/command/down")


def on_message(client: Client, userdata: Any, message: MQTTMessage) -> None:
    print(f"[CHIRPSTACK ACK SIM] command/down received. topic={message.topic}")
    try:
        topic_info = parse_chirpstack_downlink_topic(message.topic)
    except ChirpStackTopicParseError as exc:
        print(f"[CHIRPSTACK ACK SIM] Invalid topic: {exc}")
        return

    try:
        payload = json.loads(message.payload.decode("utf-8"))
    except Exception as exc:
        print(f"[CHIRPSTACK ACK SIM] Invalid payload: {exc}")
        return

    print(json.dumps(payload, indent=2))

    command_uuid, command_seq, decode_error = extract_command_metadata(payload)
    if not command_uuid:
        print("[CHIRPSTACK ACK SIM] Could not extract command_uuid from command/down payload")
        return

    if command_seq is None:
        print("[CHIRPSTACK ACK SIM] Could not extract command_seq from command/down payload")
        return

    time.sleep(1)
    publish_json(
        client,
        f"application/{topic_info.application_id}/device/{topic_info.dev_eui}/event/txack",
        build_txack_payload(command_uuid),
    )

    time.sleep(1)
    publish_json(
        client,
        f"application/{topic_info.application_id}/device/{topic_info.dev_eui}/event/ack",
        build_network_ack_payload(command_uuid),
    )

    time.sleep(1)
    status_code = simulated_ack_status_code()
    error_code = COMMAND_ACK_ERROR_NO_ERROR
    if decode_error is not None:
        status_code = COMMAND_ACK_STATUS_FAILED
        error_code = COMMAND_ACK_ERROR_INVALID_PAYLOAD

    publish_json(
        client,
        f"application/{topic_info.application_id}/device/{topic_info.dev_eui}/event/up",
        build_application_ack_payload(
            application_id=topic_info.application_id,
            dev_eui=topic_info.dev_eui,
            command_seq=command_seq,
            status_code=status_code,
            error_code=error_code,
        ),
    )


def main() -> None:
    host = mqtt_host()
    port = mqtt_port()
    tls_enabled = mqtt_tls_enabled()
    username = mqtt_username()
    password = mqtt_password()

    print(f"[CHIRPSTACK ACK SIM] Broker: {host}:{port}")
    print(f"[CHIRPSTACK ACK SIM] TLS: {tls_enabled}")
    print(f"[CHIRPSTACK ACK SIM] Username: {username}")
    print(f"[CHIRPSTACK ACK SIM] Application ACK status: {simulated_ack_status()}")

    client = Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id="chirpstack-command-ack-simulator",
    )
    if username:
        client.username_pw_set(username=username, password=password)

    if tls_enabled:
        client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.tls_insecure_set(False)

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(host=host, port=port, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
