import asyncio
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.redis.client import close_redis_client, get_redis_client
from src.service.realtime_location_publisher import LOCATION_CHANNEL
from src.settings import settings


async def main() -> None:
    redis_client = get_redis_client()

    pubsub = redis_client.pubsub()

    try:
        await redis_client.ping()

        await pubsub.subscribe(LOCATION_CHANNEL)

        print(f"[Redis] Conectado a: {settings.redis_url}")
        print(f"[Redis] Escuchando canal: {LOCATION_CHANNEL}")
        print("[Redis] Esperando mensajes...")

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                location = json.loads(message["data"])
            except json.JSONDecodeError:
                print("[Redis] Se recibió un mensaje JSON inválido")
                continue

            event_data = location.get("data", {})

            print("\n[Redis] Nueva ubicación recibida")
            print(f"Event type: {location.get('type')}")
            print(f"Version: {location.get('version')}")
            print(f"Device ID: {event_data.get('device_id')}")
            print(f"Latitude: {event_data.get('latitude')}")
            print(f"Longitude: {event_data.get('longitude')}")
            print(f"Recorded at: {event_data.get('recorded_at')}")

    finally:
        await pubsub.unsubscribe(LOCATION_CHANNEL)
        await pubsub.aclose()
        await close_redis_client()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Redis] Suscriptor detenido")
