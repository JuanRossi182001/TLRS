import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.redis.client import close_redis_client
from src.service.realtime_location_publisher import publish_location_updated


async def main() -> None:
    try:
        subscribers_count = await publish_location_updated(
            location_id=3601,
            client_id=4,
            device_id=26,
            device_serial="CHIRP-001",
            latitude=-33.6752,
            longitude=-65.4581,
            altitude=512.4,
            accuracy=8.2,
            recorded_at=datetime.now(timezone.utc),
        )

        print(
            "[Redis] Ubicación publicada. "
            f"Suscriptores: {subscribers_count}"
        )
    finally:
        await close_redis_client()


if __name__ == "__main__":
    asyncio.run(main())
