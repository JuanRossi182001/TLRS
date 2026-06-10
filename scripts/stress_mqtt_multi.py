import argparse
import hashlib
import hmac
import json
import random
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from paho.mqtt.client import Client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.settings import settings


@dataclass(frozen=True)
class StressDevice:
    serial: str
    secret: str
    topic: str


DEVICES: list[StressDevice] = [
    StressDevice(
        serial="STRESS-001",
        secret="zb0BciZwtr07eLFuyZ1BgNbiddob55G8",
        topic="gps/devices/STRESS-001/location",
    ),
    StressDevice(
        serial="STRESS-002",
        secret="jEhUE3dQ6Zed0OtwTbYB7YYWloHx1Ig1-BahCqJcgQuz7DXOOhJzSZXD91qPMJh2",
        topic="gps/devices/STRESS-002/location",
    ),
    StressDevice(
        serial="STRESS-003",
        secret="zb0BciZwtr07eLFuyZ1BgNbiddob55G8",
        topic="gps/devices/STRESS-003/location",
    ),
    StressDevice(
        serial="STRESS-004",
        secret="-Q_01tO4P-k5wJ6-zXlZLy94kDX6tGz4MbfmWIOHhV-AxJIikN4n4tBAi_KwXbvM",
        topic="gps/devices/STRESS-004/location",
    ),
    StressDevice(
        serial="STRESS-005",
        secret="zb0BciZwtr07eLFuyZ1BgNbiddob55G8",
        topic="gps/devices/STRESS-005/location",
    ),
    StressDevice(
        serial="STRESS-006",
        secret="X3V3oFXPQYHVe_IimZTSktADYmWc5m70N5PDuJ6jC1kI1ED0xfu830roiiuVQM2N",
        topic="gps/devices/STRESS-006/location",
    ),
    StressDevice(
        serial="STRESS-007",
        secret="zb0BciZwtr07eLFuyZ1BgNbiddob55G8",
        topic="gps/devices/STRESS-007/location",
    ),
    StressDevice(
        serial="STRESS-008",
        secret="jEhUE3dQ6Zed0OtwTbYB7YYWloHx1Ig1-BahCqJcgQuz7DXOOhJzSZXD91qPMJh2",
        topic="gps/devices/STRESS-008/location",
    ),
    StressDevice(
        serial="STRESS-009",
        secret="siQ_uhsAxRSPssIPW_lRyTqIw5Xr98r7sq5O0PiofQNmuAR1JycYEgscC2BJGnW0",
        topic="gps/devices/STRESS-009/location",
    ),
    StressDevice(
        serial="STRESS-010",
        secret="R0K6LRtlidbDHRWjfgdFxJgxalmGA6iQuqlqmYVj8KrB46TAwAbJab4sJkhTkMkB",
        topic="gps/devices/STRESS-010/location",
    ),
]


def build_signature(
    payload_without_signature: dict[str, Any],
    timestamp: int,
    device_secret: str,
) -> str:
    canonical_payload = json.dumps(
        payload_without_signature,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )
    message = f"{canonical_payload}{timestamp}".encode("utf-8")

    return hmac.new(
        key=device_secret.encode("utf-8"),
        msg=message,
        digestmod=hashlib.sha256,
    ).hexdigest()


def build_payload(
    device: StressDevice,
    base_lat: float,
    base_lng: float,
    jitter_degrees: float,
) -> str:
    timestamp = int(time.time())

    payload = {
        "lat": round(base_lat + random.uniform(-jitter_degrees, jitter_degrees), 7),
        "lng": round(base_lng + random.uniform(-jitter_degrees, jitter_degrees), 7),
        "timestamp": timestamp,
        "accuracy": round(random.uniform(3.0, 12.0), 2),
        "altitude": round(random.uniform(425.0, 435.0), 2),
        "speed": round(random.uniform(0.0, 2.5), 2),
        "battery": random.randint(60, 100),
        "sim_label": "stress-test",
    }

    payload["signature"] = build_signature(
        payload_without_signature=payload,
        timestamp=timestamp,
        device_secret=device.secret,
    )

    return json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )


def on_connect(client: Client, userdata, flags, reason_code, properties=None):
    print(f"[STRESS MQTT] Connected. Reason code: {reason_code}")
    userdata["connected"] = int(reason_code) == 0


def on_disconnect(client: Client, userdata, disconnect_flags, reason_code, properties=None):
    print(f"[STRESS MQTT] Disconnected. Reason code: {reason_code}")


def configure_tls(client: Client, enabled: bool) -> None:
    if not enabled:
        return

    client.tls_set(
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)


def parse_args():
    parser = argparse.ArgumentParser(description="MQTT stress test for multiple GPS devices.")

    parser.add_argument("--broker-host", default=settings.mqtt_host)
    parser.add_argument("--broker-port", type=int, default=settings.mqtt_port)
    parser.add_argument(
        "--tls",
        action=argparse.BooleanOptionalAction,
        default=settings.mqtt_tls_enabled,
    )

    parser.add_argument("--mqtt-username", default="stress_tester")
    parser.add_argument("--mqtt-password", default="tester123", required=True)

    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--qos", type=int, choices=(0, 1, 2), default=1)

    parser.add_argument("--base-lat", type=float, default=-33.6750)
    parser.add_argument("--base-lng", type=float, default=-65.4610)
    parser.add_argument("--jitter-degrees", type=float, default=0.0005)

    parser.add_argument("--dry-run", action="store_true")

    return parser.parse_args()


def main():
    args = parse_args()

    print("[STRESS MQTT] Starting stress test")
    print(f"[STRESS MQTT] Broker: {args.broker_host}:{args.broker_port}")
    print(f"[STRESS MQTT] TLS: {args.tls}")
    print(f"[STRESS MQTT] MQTT user: {args.mqtt_username}")
    print(f"[STRESS MQTT] Devices: {len(DEVICES)}")
    print(f"[STRESS MQTT] Interval: {args.interval}s")
    print(f"[STRESS MQTT] Duration: {args.duration}s")
    print(f"[STRESS MQTT] QoS: {args.qos}")

    if args.dry_run:
        for device in DEVICES:
            payload = build_payload(
                device=device,
                base_lat=args.base_lat,
                base_lng=args.base_lng,
                jitter_degrees=args.jitter_degrees,
            )
            print()
            print(f"[DRY RUN] Device: {device.serial}")
            print(f"[DRY RUN] Topic: {device.topic}")
            print(f"[DRY RUN] Payload: {payload}")
        return

    client = Client(
        client_id=f"stress-tester-{int(time.time())}",
        userdata={"connected": False},
    )

    client.username_pw_set(
        username=args.mqtt_username,
        password=args.mqtt_password,
    )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    configure_tls(client, args.tls)

    client.connect(
        host=args.broker_host,
        port=args.broker_port,
        keepalive=60,
    )
    client.loop_start()

    for _ in range(50):
        if client._userdata["connected"]:
            break
        time.sleep(0.1)

    if not client._userdata["connected"]:
        raise RuntimeError("MQTT connection was not accepted by the broker.")

    started_at = time.time()
    deadline = started_at + args.duration

    sent_count = 0
    failed_count = 0
    cycle_count = 0

    try:
        while time.time() < deadline:
            cycle_count += 1
            cycle_started_at = time.time()

            for device in DEVICES:
                payload = build_payload(
                    device=device,
                    base_lat=args.base_lat,
                    base_lng=args.base_lng,
                    jitter_degrees=args.jitter_degrees,
                )

                result = client.publish(
                    topic=device.topic,
                    payload=payload,
                    qos=args.qos,
                )

                #result.wait_for_publish()

                if result.rc == 0:
                    sent_count += 1
                else:
                    failed_count += 1
                    print(
                        f"[STRESS MQTT] Publish failed. "
                        f"device={device.serial} rc={result.rc}"
                    )

            now = datetime.now(UTC).isoformat()
            elapsed = time.time() - started_at

            print(
                f"[STRESS MQTT] Cycle #{cycle_count} | "
                f"sent={sent_count} failed={failed_count} "
                f"elapsed={elapsed:.1f}s at={now}"
            )

            cycle_elapsed = time.time() - cycle_started_at
            sleep_time = max(0.0, args.interval - cycle_elapsed)

            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[STRESS MQTT] Stopping stress test...")

    finally:
        total_elapsed = time.time() - started_at
        msg_per_second = sent_count / total_elapsed if total_elapsed > 0 else 0

        print()
        print("[STRESS MQTT] Summary")
        print(f"[STRESS MQTT] Sent: {sent_count}")
        print(f"[STRESS MQTT] Failed: {failed_count}")
        print(f"[STRESS MQTT] Duration: {total_elapsed:.2f}s")
        print(f"[STRESS MQTT] Approx msg/s: {msg_per_second:.2f}")

        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()