import argparse
import hashlib
import hmac
import json
import math
import random
import ssl
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from paho.mqtt.client import Client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.settings import settings


DEFAULT_SHAPE_HEX = (
    "0106000020E61000000100000001030000000100000005000000"
    "B20E8A6EDC5B50C0C9D6C1A24DD740C0"
    "9D7BA6F1F65B50C039D47D15F0D740C0"
    "54A30A685E5B50C0017D96142BD840C0"
    "AC5A1E89465B50C0ABC9173588D740C0"
    "B20E8A6EDC5B50C0C9D6C1A24DD740C0"
)


@dataclass(frozen=True)
class Point:
    lng: float
    lat: float


@dataclass(frozen=True)
class TimedPoint:
    point: Point
    accuracy: float
    label: str


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
    timed_point: TimedPoint,
    device_secret: str,
    altitude: float,
) -> str:
    timestamp = int(time.time())
    payload = {
        "lat": round(timed_point.point.lat, 7),
        "lng": round(timed_point.point.lng, 7),
        "timestamp": timestamp,
        "accuracy": round(timed_point.accuracy, 2),
        "altitude": altitude,
        "sim_label": timed_point.label,
    }
    payload["signature"] = build_signature(payload, timestamp, device_secret)
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def build_route(
    multipolygon: list[list[list[Point]]],
    scenario: str,
    repeats: int,
    jitter_meters: float,
) -> list[TimedPoint]:
    outer_ring = multipolygon[0][0]
    center = polygon_centroid(outer_ring)
    boundary_points = outer_ring[:-1]

    route_builders = {
        "inside": build_inside_route,
        "exit-return": build_exit_return_route,
        "boundary-noise": build_boundary_noise_route,
        "mixed": build_mixed_route,
    }

    route = route_builders[scenario](
        center=center,
        boundary_points=boundary_points,
        jitter_meters=jitter_meters,
    )

    return route * repeats


def build_inside_route(
    center: Point,
    boundary_points: list[Point],
    jitter_meters: float,
) -> list[TimedPoint]:
    route = []
    for boundary in boundary_points:
        for ratio in (0.20, 0.35, 0.50, 0.65):
            route.append(
                TimedPoint(
                    point=jitter(interpolate(center, boundary, ratio), jitter_meters),
                    accuracy=random.uniform(3.0, 8.0),
                    label="inside",
                )
            )
    return route


def build_exit_return_route(
    center: Point,
    boundary_points: list[Point],
    jitter_meters: float,
) -> list[TimedPoint]:
    boundary = farthest_point(center, boundary_points)
    ratios = (0.20, 0.55, 0.88, 0.99, 1.03, 1.12, 1.22, 1.08, 0.98, 0.75, 0.40)
    labels = (
        "inside",
        "inside",
        "near-limit",
        "near-limit",
        "outside",
        "outside",
        "outside",
        "outside",
        "near-limit-return",
        "inside-return",
        "inside",
    )
    return [
        TimedPoint(
            point=jitter(interpolate(center, boundary, ratio), jitter_meters),
            accuracy=random.uniform(3.0, 10.0),
            label=label,
        )
        for ratio, label in zip(ratios, labels, strict=True)
    ]


def build_boundary_noise_route(
    center: Point,
    boundary_points: list[Point],
    jitter_meters: float,
) -> list[TimedPoint]:
    boundary = farthest_point(center, boundary_points)
    route = []
    for ratio in (0.94, 0.98, 1.01, 0.99, 1.02, 0.97, 1.04, 0.96):
        route.append(
            TimedPoint(
                point=jitter(interpolate(center, boundary, ratio), jitter_meters),
                accuracy=random.choice([6.0, 12.0, 35.0, 45.0]),
                label="boundary-noise",
            )
        )
    return route


def build_mixed_route(
    center: Point,
    boundary_points: list[Point],
    jitter_meters: float,
) -> list[TimedPoint]:
    return (
        build_inside_route(center, boundary_points, jitter_meters)
        + build_exit_return_route(center, boundary_points, jitter_meters)
        + build_boundary_noise_route(center, boundary_points, jitter_meters)
    )


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


def on_connect(client: Client, userdata, flags, reason_code, properties=None):
    print(f"[DEVICE SIM] Connected to MQTT broker. Reason code: {reason_code}")
    userdata["connected"] = int(reason_code) == 0


def on_disconnect(client: Client, userdata, disconnect_flags, reason_code, properties=None):
    print(f"[DEVICE SIM] Disconnected from MQTT broker. Reason code: {reason_code}")


def on_publish(client: Client, userdata, mid, reason_code=None, properties=None):
    print(f"[DEVICE SIM] Publish acknowledged. mid={mid} reason_code={reason_code}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Simulate MQTT GPS telemetry around a PostGIS EWKB geofence."
    )
    parser.add_argument("--broker-host", default=settings.mqtt_host)
    parser.add_argument("--broker-port", type=int, default=settings.mqtt_port)
    parser.add_argument("--tls", action=argparse.BooleanOptionalAction, default=settings.mqtt_tls_enabled)
    parser.add_argument("--mqtt-username", default="device_AAA-001")
    parser.add_argument("--mqtt-password", default="AShZmtyVOGgGspWP")
    parser.add_argument("--device-serial", default="AAA-001")
    parser.add_argument("--device-secret", default="zb0BciZwtr07eLFuyZ1BgNbiddob55G8")
    parser.add_argument("--topic", default=None)
    parser.add_argument("--shape-hex", default=DEFAULT_SHAPE_HEX)
    parser.add_argument(
        "--scenario",
        choices=("inside", "exit-return", "boundary-noise", "mixed"),
        default="mixed",
    )
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--jitter-meters", type=float, default=4.0)
    parser.add_argument("--altitude", type=float, default=430.5)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def configure_tls(client: Client, enabled: bool) -> None:
    if not enabled:
        return

    client.tls_set(
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)


def main():
    args = parse_args()
    topic = args.topic or f"gps/devices/{args.device_serial}/location"
    multipolygon = EwkbReader(args.shape_hex).read_multipolygon()
    route = build_route(
        multipolygon=multipolygon,
        scenario=args.scenario,
        repeats=args.repeats,
        jitter_meters=args.jitter_meters,
    )

    print("[DEVICE SIM] Starting simulated device")
    print(f"[DEVICE SIM] Broker: {args.broker_host}:{args.broker_port}")
    print(f"[DEVICE SIM] MQTT user: {args.mqtt_username}")
    print(f"[DEVICE SIM] MQTT TLS: {args.tls}")
    print(f"[DEVICE SIM] Topic: {topic}")
    print(f"[DEVICE SIM] Scenario: {args.scenario}")
    print(f"[DEVICE SIM] Points: {len(route)}")

    if args.dry_run:
        for index, timed_point in enumerate(route, start=1):
            payload = build_payload(timed_point, args.device_secret, args.altitude)
            print(f"[DEVICE SIM] #{index:03d} {timed_point.label}: {payload}")
        return

    client = Client(
        client_id=f"simulator-{args.device_serial}",
        userdata={"connected": False},
    )
    client.username_pw_set(
        username=args.mqtt_username,
        password=args.mqtt_password,
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish = on_publish
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

    try:
        for index, timed_point in enumerate(route, start=1):
            payload = build_payload(timed_point, args.device_secret, args.altitude)
            result = client.publish(
                topic=topic,
                payload=payload,
                qos=1,
            )
            result.wait_for_publish()
            if result.rc != 0:
                raise RuntimeError(f"MQTT publish failed with result code: {result.rc}")

            print()
            print(f"[DEVICE SIM] Published #{index}/{len(route)} at {datetime.utcnow().isoformat()} UTC")
            print(f"[DEVICE SIM] Label: {timed_point.label}")
            print(f"[DEVICE SIM] Payload: {payload}")

            if index < len(route):
                time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[DEVICE SIM] Stopping simulator...")

    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
