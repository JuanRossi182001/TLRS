from datetime import datetime

from src.infrastructure.redis.client import get_redis_client
from src.schemas.realtime_location import (
    RealtimeLocationData,
    RealtimeLocationUpdatedEvent,
)


LOCATION_CHANNEL = "manea:locations"


async def publish_location_updated(
    *,
    location_id: int,
    client_id: int,
    device_id: int,
    device_serial: str,
    latitude: float,
    longitude: float,
    altitude: float | None,
    accuracy: float | None,
    recorded_at: datetime,
) -> int:
    event = RealtimeLocationUpdatedEvent(
        data=RealtimeLocationData(
            location_id=location_id,
            client_id=client_id,
            device_id=device_id,
            device_serial=device_serial,
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
            accuracy=accuracy,
            recorded_at=recorded_at,
        )
    )

    subscribers_count = await get_redis_client().publish(
        LOCATION_CHANNEL,
        event.model_dump_json(),
    )

    return subscribers_count
