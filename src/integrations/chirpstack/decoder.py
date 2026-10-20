from datetime import datetime, timezone

from src.application.telemetry.normalized_telemetry import NormalizedTelemetry
from src.integrations.chirpstack.payload_codec import decode_location_payload_v1
from src.integrations.chirpstack.schemas import ChirpStackUpEvent


class ChirpStackDecodeError(ValueError):
    pass


def decode_up_event(event: ChirpStackUpEvent) -> NormalizedTelemetry:
    event_object = event.object
    if event_object is not None and event_object.lat is not None and event_object.lng is not None:
        return _decode_from_object(event)

    try:
        return decode_location_payload_v1(event)
    except ValueError as exc:
        raise ChirpStackDecodeError(str(exc)) from exc


def _decode_from_object(event: ChirpStackUpEvent) -> NormalizedTelemetry:
    event_object = event.object
    if event_object is None:
        raise ChirpStackDecodeError("Missing object payload in ChirpStack up event")

    latitude = float(event_object.lat)
    longitude = float(event_object.lng)

    if latitude < -90 or latitude > 90:
        raise ChirpStackDecodeError("Latitude out of range")

    if longitude < -180 or longitude > 180:
        raise ChirpStackDecodeError("Longitude out of range")

    return NormalizedTelemetry(
        device_timestamp=_to_utc_naive(event.time),
        latitude=latitude,
        longitude=longitude,
        altitude=event_object.altitude,
        accuracy=event_object.accuracy,
        extra={
            "battery": event_object.battery,
            "f_port": event.fPort,
            "gateway_ids": [item.gatewayId for item in event.rxInfo if item.gatewayId],
            "device_name": event.deviceInfo.deviceName,
            "serial": event.deviceInfo.tags.get("serial"),
            "payload_format": "chirpstack_object",
        },
    )


def _to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value

    return value.astimezone(timezone.utc).replace(tzinfo=None)
