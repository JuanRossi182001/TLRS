from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class LocationPayload(BaseModel):
    device_serial: str = Field(min_length=1, max_length=100)

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)

    timestamp: int

    accuracy: float | None = None
    altitude: float | None = None
    speed: float | None = None
    battery: int | None = Field(default=None, ge=0, le=100)


def extract_device_serial_from_topic(topic: str) -> str | None:
    """
    Expected topic:
    gps/devices/AAA-001/location
    """

    parts = topic.split("/")

    if len(parts) != 4:
        return None

    prefix, entity, device_serial, event_type = parts

    if prefix != "gps":
        return None

    if entity != "devices":
        return None

    if event_type != "location":
        return None

    if not device_serial:
        return None

    return device_serial


def validate_location_message(
    topic: str,
    payload_data: dict[str, Any],
) -> tuple[bool, str, LocationPayload | None]:
    topic_device_serial = extract_device_serial_from_topic(topic)

    if topic_device_serial is None:
        return False, "INVALID_TOPIC", None

    try:
        payload = LocationPayload.model_validate(payload_data)
    except ValidationError as exc:
        return False, f"INVALID_PAYLOAD: {exc.errors()}", None

    if payload.device_serial != topic_device_serial:
        return False, "DEVICE_SERIAL_MISMATCH", None

    now = int(datetime.now(timezone.utc).timestamp())

    # No aceptar datos con más de 5 minutos en el futuro.
    if payload.timestamp > now + 300:
        return False, "TIMESTAMP_FROM_FUTURE", None

    # Para desarrollo, podemos aceptar datos viejos.
    # Después podemos endurecer esto:
    # if payload.timestamp < now - 3600:
    #     return False, "TIMESTAMP_TOO_OLD", None

    return True, "OK", payload