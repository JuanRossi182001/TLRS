from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_serializer, field_validator


def _normalize_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)


class RealtimeLocationData(BaseModel):
    location_id: int
    client_id: int
    device_id: int
    device_serial: str
    latitude: float
    longitude: float
    altitude: float | None = None
    accuracy: float | None = None
    recorded_at: datetime

    @field_validator("recorded_at", mode="before")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        return _normalize_utc_datetime(value)

    @field_serializer("recorded_at")
    def serialize_recorded_at(self, value: datetime) -> str:
        return _normalize_utc_datetime(value).isoformat()


class RealtimeLocationUpdatedEvent(BaseModel):
    version: Literal[1] = 1
    type: Literal["device.location.updated"] = "device.location.updated"
    data: RealtimeLocationData
