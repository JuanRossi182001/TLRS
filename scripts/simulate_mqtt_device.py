import json
import time
import hmac
import hashlib
from datetime import datetime
from typing import Any

from paho.mqtt.client import Client


BROKER_HOST = "localhost"
BROKER_PORT = 1883

MQTT_USERNAME = "device_aaa_001"
MQTT_PASSWORD = "device123"

DEVICE_SERIAL = "AAA-001"
TOPIC = f"gps/devices/{DEVICE_SERIAL}/location"


# Tiene que ser el mismo secret guardado en DeviceCredential.secret
DEVICE_SECRET = "zb0BciZwtr07eLFuyZ1BgNbiddob55G8"



def build_signature(payload_without_signature: dict[str, Any], timestamp: int) -> str:
    """
    Builds the same HMAC signature expected by the backend for MQTT.

    Rule:
    compact_sorted_payload_without_signature + timestamp
    """

    canonical_payload = json.dumps(
        payload_without_signature,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )

    message = f"{canonical_payload}{timestamp}".encode("utf-8")

    return hmac.new(
        key=DEVICE_SECRET.encode("utf-8"),
        msg=message,
        digestmod=hashlib.sha256,
    ).hexdigest()


def build_payload() -> str:
    timestamp = int(time.time())

    payload = {
        "lat": -31.4135,
        "lng": -64.1810,
        "timestamp": timestamp,
        "accuracy": 4.2,
        "altitude": 430.5,
    }

    signature = build_signature(payload, timestamp)

    payload["signature"] = signature

    return json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )


def on_connect(client: Client, userdata, flags, reason_code, properties=None):
    print(f"[DEVICE SIM] Connected to MQTT broker. Reason code: {reason_code}")


def on_disconnect(client: Client, userdata, disconnect_flags, reason_code, properties=None):
    print(f"[DEVICE SIM] Disconnected from MQTT broker. Reason code: {reason_code}")


def main():
    client = Client(client_id=f"simulator-{DEVICE_SERIAL}")

    client.username_pw_set(
        username=MQTT_USERNAME,
        password=MQTT_PASSWORD,
    )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    print("[DEVICE SIM] Starting simulated device")
    print(f"[DEVICE SIM] Broker: {BROKER_HOST}:{BROKER_PORT}")
    print(f"[DEVICE SIM] Topic: {TOPIC}")

    client.connect(
        host=BROKER_HOST,
        port=BROKER_PORT,
        keepalive=60,
    )

    client.loop_start()

    try:
        while True:
            payload = build_payload()

            result = client.publish(
                topic=TOPIC,
                payload=payload,
                qos=1,
            )

            result.wait_for_publish()

            print()
            print(f"[DEVICE SIM] Published at {datetime.utcnow().isoformat()} UTC")
            print(f"[DEVICE SIM] Topic: {TOPIC}")
            print(f"[DEVICE SIM] Payload: {payload}")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\n[DEVICE SIM] Stopping simulator...")

    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()