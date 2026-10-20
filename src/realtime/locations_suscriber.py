import asyncio
import logging

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.realtime.connection_manager import ConnectionManager
from src.schemas.realtime_location import RealtimeLocationUpdatedEvent


LOCATION_CHANNEL = "manea:locations"
logger = logging.getLogger(__name__)


async def listen_location_events(
    redis_client: Redis,
    connection_manager: ConnectionManager,
) -> None:
    while True:
        try:
            async with redis_client.pubsub() as pubsub:
                await pubsub.subscribe(LOCATION_CHANNEL)
                logger.info(
                    "Realtime location subscriber ready. channel=%s",
                    LOCATION_CHANNEL,
                )

                try:
                    async for message in pubsub.listen():
                        if message["type"] != "message":
                            continue

                        try:
                            event = (
                                RealtimeLocationUpdatedEvent.model_validate_json(
                                    message["data"]
                                )
                            )
                        except ValidationError:
                            logger.warning(
                                "Ignoring invalid realtime location event from Redis. channel=%s",
                                LOCATION_CHANNEL,
                            )
                            continue

                        try:
                            await connection_manager.send_to_client(
                                client_id=event.data.client_id,
                                payload=event.model_dump(mode="json"),
                            )
                        except Exception:
                            logger.exception(
                                "Unexpected realtime location dispatch error. channel=%s client_id=%s",
                                LOCATION_CHANNEL,
                                event.data.client_id,
                            )
                finally:
                    await pubsub.unsubscribe(LOCATION_CHANNEL)

        except asyncio.CancelledError:
            raise
        except RedisError as exc:
            logger.exception(
                "Realtime location subscriber failed due to Redis error and will retry. channel=%s error=%s",
                LOCATION_CHANNEL,
                exc,
            )
        except Exception:
            logger.exception(
                "Realtime location subscriber failed unexpectedly and will retry. channel=%s",
                LOCATION_CHANNEL,
            )

        await asyncio.sleep(1)
