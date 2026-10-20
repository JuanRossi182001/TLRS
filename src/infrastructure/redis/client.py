from redis.asyncio import Redis

from src.settings import settings

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
)


def get_redis_client() -> Redis:
    return redis_client


async def close_redis_client() -> None:
    await redis_client.aclose()
