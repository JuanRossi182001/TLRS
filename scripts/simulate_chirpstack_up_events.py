import base64
import json
import math
import os
import random
import ssl
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from paho.mqtt.client import CallbackAPIVersion, Client, MQTT_ERR_SUCCESS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.chirpstack.binary_contract import (
    GPS_FIX_GPS,
    LOCATION_MESSAGE_TYPE,
    PROTOCOL_VERSION_V1,
)
from src.settings import settings


DEFAULT_STATIC_POINTS = [
    {"lat": -33.3012, "lng": -66.3371, "altitude": 520.4, "accuracy": 4.8, "battery": 87},
    {"lat": -33.30105, "lng": -66.33685, "altitude": 521.0, "accuracy": 4.6, "battery": 86},
    {"lat": -33.3009, "lng": -66.33655, "altitude": 521.7, "accuracy": 4.9, "battery": 85},
]


@dataclass(frozen=True)
class Point:
    lng: float
    lat: float


class EwkbReader:
    def __init__(self, hex_value: str):
        self.data = bytes.fromhex("".join(hex_value.split()))
        self.offset = 0

    def read_multipolygon(self) -> list[list[list[Point]]]:
        byte_order, geometry_type = self._read_header()
        endian = self._endian(byte_order)

        has_srid = bool(geometry_type & 0x20000000)
        base_type = geometry_type & 0x000000FF
        if base_type != 6:
            raise ValueError("The provided shape must be an EWKB MultiPolygon.")

        if has_srid:
            self._read_uint32(endian)

        polygon_count = self._read_uint32(endian)
        return [self._read_polygon() for _ in range(polygon_count)]

    def _read_polygon(self) -> list[list[Point]]:
        byte_order, geometry_type = self._read_header()
        endian = self._endian(byte_order)
        base_type = geometry_type & 0x000000FF
        if base_type != 3:
            raise ValueError("Expected Polygon inside MultiPolygon EWKB.")

        ring_count = self._read_uint32(endian)
        rings = []
        for _ in range(ring_count):
            point_count = self._read_uint32(endian)
            ring = []
            for _ in range(point_count):
                lng = self._read_double(endian)
                lat = self._read_double(endian)
                ring.append(Point(lng=lng, lat=lat))
            rings.append(ring)

        return rings

    def _read_header(self) -> tuple[int, int]:
        byte_order = self.data[self.offset]
        self.offset += 1
        endian = self._endian(byte_order)
        geometry_type = self._read_uint32(endian)
        return byte_order, geometry_type

    def _read_uint32(self, endian: str) -> int:
        value = struct.unpack_from(f"{endian}I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def _read_double(self, endian: str) -> float:
        value = struct.unpack_from(f"{endian}d", self.data, self.offset)[0]
        self.offset += 8
        return value

    def _endian(self, byte_order: int) -> str:
        if byte_order == 0:
            return ">"
        if byte_order == 1:
            return "<"
        raise ValueError("Invalid EWKB byte order.")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def mqtt_host() -> str:
    return os.getenv("CHIRPSTACK_MQTT_HOST") or settings.chirpstack_event_mqtt_host


def mqtt_port() -> int:
    return int(os.getenv("CHIRPSTACK_MQTT_PORT") or settings.chirpstack_event_mqtt_port)


def mqtt_username() -> str | None:
    return os.getenv("CHIRPSTACK_MQTT_USERNAME") or settings.chirpstack_event_mqtt_username


def mqtt_password() -> str | None:
    return os.getenv("CHIRPSTACK_MQTT_PASSWORD") or settings.chirpstack_event_mqtt_password


def mqtt_tls_enabled() -> bool:
    if "CHIRPSTACK_MQTT_USE_TLS" in os.environ:
        return env_bool("CHIRPSTACK_MQTT_USE_TLS")
    return settings.chirpstack_event_mqtt_tls_enabled


def build_messages(
    application_id: str,
    dev_eui: str,
    run_id: str,
    points: list[dict[str, float]],
) -> list[tuple[str, dict]]:
    topic = f"application/{application_id}/device/{dev_eui}/event/up"
    tenant_id = os.getenv("CHIRPSTACK_TENANT_ID", "manea-tenant-dev")
    tenant_name = os.getenv("CHIRPSTACK_TENANT_NAME", "Manea")
    application_name = os.getenv("CHIRPSTACK_APPLICATION_NAME", "Manea Dev")
    device_profile_id = os.getenv("CHIRPSTACK_DEVICE_PROFILE_ID", "collar-gps-profile")
    device_profile_name = os.getenv("CHIRPSTACK_DEVICE_PROFILE_NAME", "Collar GPS")
    device_name = os.getenv("CHIRPSTACK_DEVICE_NAME", "Collar 001")
    device_serial = os.getenv("CHIRPSTACK_DEVICE_SERIAL", "COLLAR-001")
    gateway_primary = os.getenv("CHIRPSTACK_GATEWAY_ID", "gateway-sim-001")
    gateway_secondary = os.getenv("CHIRPSTACK_GATEWAY_ID_SECONDARY", "gateway-sim-002")
    payload_format = os.getenv("CHIRPSTACK_SIM_FORMAT", "binary").strip().lower()
    messages: list[tuple[str, dict]] = []
    for index, point in enumerate(points, start=1):
        payload = {
            "deduplicationId": f"sim-{dev_eui}-{run_id}-{index}",
            "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "deviceInfo": {
                "tenantId": tenant_id,
                "tenantName": tenant_name,
                "applicationId": application_id,
                "applicationName": application_name,
                "deviceProfileId": device_profile_id,
                "deviceProfileName": device_profile_name,
                "deviceName": device_name,
                "devEui": dev_eui,
                "tags": {"serial": device_serial},
            },
            "fPort": 10,
            "rxInfo": [
                {
                    "gatewayId": gateway_primary,
                    "rssi": -72,
                    "snr": 8.5,
                },
                {
                    "gatewayId": gateway_secondary,
                    "rssi": -75,
                    "snr": 7.9,
                },
            ],
        }

        if payload_format == "legacy":
            payload["object"] = point
        else:
            payload["data"] = encode_location_payload(point)

        messages.append((topic, payload))

    return messages


def encode_location_payload(point: dict[str, float]) -> str:
    payload = struct.pack(
        ">BBiihBBB",
        PROTOCOL_VERSION_V1,
        LOCATION_MESSAGE_TYPE,
        int(round(float(point["lat"]) * 10_000_000)),
        int(round(float(point["lng"]) * 10_000_000)),
        int(round(float(point["altitude"]))),
        max(0, min(255, int(round(float(point["accuracy"]))))),
        max(0, min(255, int(round(float(point["battery"]))))),
        GPS_FIX_GPS,
    )
    return base64.b64encode(payload).decode("ascii")


def build_points_for_scenario() -> tuple[str, list[dict[str, float]]]:
    scenario = os.getenv("CHIRPSTACK_SIM_SCENARIO", "static").strip().lower()
    if scenario == "static":
        return scenario, DEFAULT_STATIC_POINTS

    shape_hex = os.getenv("CHIRPSTACK_SHAPE_HEX")
    if not shape_hex:
        raise ValueError(
            "CHIRPSTACK_SHAPE_HEX is required when CHIRPSTACK_SIM_SCENARIO is not 'static'"
        )

    multipolygon = EwkbReader(shape_hex).read_multipolygon()
    outer_ring = multipolygon[0][0]
    center = polygon_centroid(outer_ring)
    boundary = farthest_point(center, outer_ring[:-1])
    altitude = float(os.getenv("CHIRPSTACK_SIM_ALTITUDE", "520.4"))
    battery_start = int(os.getenv("CHIRPSTACK_SIM_BATTERY_START", "87"))
    jitter_meters = float(os.getenv("CHIRPSTACK_SIM_JITTER_METERS", "0"))

    if scenario == "inside-outside":
        route = [
            (0.20, 4.8, "inside"),
            (0.72, 4.6, "near-limit"),
            (1.18, 4.9, "outside"),
        ]
    elif scenario == "outside-only":
        route = [
            (1.10, 4.8, "outside"),
            (1.18, 4.6, "outside"),
            (1.26, 4.9, "outside"),
        ]
    else:
        raise ValueError(
            "CHIRPSTACK_SIM_SCENARIO must be one of: static, inside-outside, outside-only"
        )

    points: list[dict[str, float]] = []
    for index, (ratio, accuracy, label) in enumerate(route):
        point = jitter(interpolate(center, boundary, ratio), jitter_meters)
        points.append(
            {
                "lat": round(point.lat, 7),
                "lng": round(point.lng, 7),
                "altitude": altitude + (index * 0.5),
                "accuracy": accuracy,
                "battery": battery_start - index,
                "sim_label": label,
            }
        )

    return scenario, points


def polygon_centroid(ring: list[Point]) -> Point:
    points = ring[:-1] if ring[0] == ring[-1] else ring
    signed_area = 0.0
    centroid_lng = 0.0
    centroid_lat = 0.0

    for current, next_point in pairs(points):
        cross = current.lng * next_point.lat - next_point.lng * current.lat
        signed_area += cross
        centroid_lng += (current.lng + next_point.lng) * cross
        centroid_lat += (current.lat + next_point.lat) * cross

    signed_area *= 0.5
    if abs(signed_area) < 0.000000001:
        return Point(
            lng=sum(point.lng for point in points) / len(points),
            lat=sum(point.lat for point in points) / len(points),
        )

    return Point(
        lng=centroid_lng / (6.0 * signed_area),
        lat=centroid_lat / (6.0 * signed_area),
    )


def pairs(points: list[Point]) -> Iterable[tuple[Point, Point]]:
    for index, point in enumerate(points):
        yield point, points[(index + 1) % len(points)]


def farthest_point(origin: Point, points: list[Point]) -> Point:
    return max(points, key=lambda point: distance_degrees(origin, point))


def interpolate(start: Point, end: Point, ratio: float) -> Point:
    return Point(
        lng=start.lng + (end.lng - start.lng) * ratio,
        lat=start.lat + (end.lat - start.lat) * ratio,
    )


def jitter(point: Point, jitter_meters: float) -> Point:
    if jitter_meters <= 0:
        return point

    meters_per_degree_lat = 111_320.0
    meters_per_degree_lng = meters_per_degree_lat * math.cos(math.radians(point.lat))
    return Point(
        lng=point.lng + random.uniform(-jitter_meters, jitter_meters) / meters_per_degree_lng,
        lat=point.lat + random.uniform(-jitter_meters, jitter_meters) / meters_per_degree_lat,
    )


def distance_degrees(first: Point, second: Point) -> float:
    return math.hypot(first.lng - second.lng, first.lat - second.lat)


def main() -> None:
    application_id = os.getenv("CHIRPSTACK_APPLICATION_ID", "f6d0cd7d-2f07-4c4b-8378-dde130fe5699")
    dev_eui = os.getenv("CHIRPSTACK_DEV_EUI", "0102030405060708").replace(" ", "").lower()
    interval_seconds = float(os.getenv("CHIRPSTACK_SIM_INTERVAL_SECONDS", "3"))
    run_id = os.getenv("CHIRPSTACK_SIM_RUN_ID", uuid4().hex[:8])
    scenario, points = build_points_for_scenario()

    host = mqtt_host()
    port = mqtt_port()
    tls_enabled = mqtt_tls_enabled()

    client = Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=f"chirpstack-simulator-{dev_eui}",
    )
    username = mqtt_username()
    password = mqtt_password()
    if username:
        client.username_pw_set(username=username, password=password)

    if tls_enabled:
        client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.tls_insecure_set(False)

    print(f"[CHIRPSTACK SIM] Broker: {host}:{port}")
    print(f"[CHIRPSTACK SIM] TLS: {tls_enabled}")
    print(f"[CHIRPSTACK SIM] Username: {username}")
    print(f"[CHIRPSTACK SIM] Application ID: {application_id}")
    print(f"[CHIRPSTACK SIM] DevEUI: {dev_eui}")
    print(f"[CHIRPSTACK SIM] Run ID: {run_id}")
    print(f"[CHIRPSTACK SIM] Scenario: {scenario}")

    client.connect(host=host, port=port, keepalive=60)
    client.loop_start()

    try:
        for topic, payload in build_messages(application_id, dev_eui, run_id, points):
            print(f"[CHIRPSTACK SIM] Publishing to {topic}")
            print(json.dumps(payload, indent=2))
            result = client.publish(topic=topic, payload=json.dumps(payload), qos=1)
            result.wait_for_publish(timeout=10)
            if result.rc != MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed with rc={result.rc}")
            time.sleep(interval_seconds)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
