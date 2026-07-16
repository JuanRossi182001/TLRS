import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from src.service.realtime_location_publisher import (
    LOCATION_CHANNEL,
    publish_location_updated,
)


class RealtimeLocationPublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_location_updated_uses_versioned_contract(self) -> None:
        redis_client = type(
            "RedisClientStub",
            (),
            {"publish": AsyncMock(return_value=2)},
        )()

        with patch(
            "src.service.realtime_location_publisher.get_redis_client",
            return_value=redis_client,
        ):
            subscribers_count = await publish_location_updated(
                location_id=3601,
                client_id=4,
                device_id=26,
                device_serial="CHIRP-001",
                latitude=-33.6752,
                longitude=-65.4581,
                altitude=None,
                accuracy=None,
                recorded_at=datetime(2026, 7, 16, 13, 20, 0),
            )

        redis_client.publish.assert_awaited_once()
        channel, message = redis_client.publish.await_args.args
        payload = json.loads(message)

        self.assertEqual(channel, LOCATION_CHANNEL)
        self.assertEqual(subscribers_count, 2)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["type"], "device.location.updated")
        self.assertEqual(payload["data"]["location_id"], 3601)
        self.assertEqual(payload["data"]["client_id"], 4)
        self.assertEqual(payload["data"]["device_id"], 26)
        self.assertEqual(payload["data"]["device_serial"], "CHIRP-001")
        self.assertEqual(payload["data"]["latitude"], -33.6752)
        self.assertEqual(payload["data"]["longitude"], -65.4581)
        self.assertIsNone(payload["data"]["altitude"])
        self.assertIsNone(payload["data"]["accuracy"])
        self.assertEqual(payload["data"]["recorded_at"], "2026-07-16T13:20:00+00:00")


if __name__ == "__main__":
    unittest.main()
