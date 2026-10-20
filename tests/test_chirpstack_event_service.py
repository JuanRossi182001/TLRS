import base64
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from redis.exceptions import RedisError

from src.application.telemetry.normalized_telemetry import NormalizedTelemetry
from src.integrations.chirpstack.service import ChirpStackEventService, ChirpStackHandleResult
from src.models.chirpstack_event import ChirpStackEvent
from src.models.device import Device, DeviceCommunicationProtocol, DeviceState
from src.models.device_command import DeviceCommandStatus
from src.schemas.realtime_location import RealtimeLocationData
from src.service.device_command_ack_service import DeviceCommandAckResult


class FakeSession:
    def __init__(self, commit_side_effects=None, asset_client_id_by_asset_id=None) -> None:
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self.next_event_id = 1
        self.commit_side_effects = list(commit_side_effects or [])
        self.asset_client_id_by_asset_id = asset_client_id_by_asset_id or {}
        self.last_event: ChirpStackEvent | None = None

    def add(self, value) -> None:
        self.added.append(value)
        if isinstance(value, ChirpStackEvent):
            self.last_event = value

    async def flush(self) -> None:
        self.flush_count += 1
        if self.last_event is not None and self.last_event.id is None:
            self.last_event.id = self.next_event_id
            self.next_event_id += 1

    async def commit(self) -> None:
        self.commit_count += 1
        if self.commit_side_effects:
            effect = self.commit_side_effects.pop(0)
            if effect is not None:
                raise effect

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def refresh(self, value) -> None:
        return None

    async def execute(self, stmt):
        class Result:
            def __init__(self, value):
                self.value = value

            def scalar_one_or_none(self):
                return self.value

        params = stmt.compile().params
        asset_id = params.get("id_asset_1")
        return Result(self.asset_client_id_by_asset_id.get(asset_id))


class RoutingEventService(ChirpStackEventService):
    def __init__(self, device, up_event):
        super().__init__(FakeSession())
        self.device = device
        self.up_event = up_event

    async def _get_device(self, dev_eui: str):
        return self.device

    def _validate_up_event(self, payload: dict, dev_eui: str):
        return self.up_event


class HandleEventService(ChirpStackEventService):
    def __init__(self, db: FakeSession, process_result: ChirpStackHandleResult):
        super().__init__(db)
        self.process_result = process_result

    async def _event_exists(self, deduplication_id: str) -> bool:
        return False

    async def _process_up_event(
        self,
        application_id: str,
        dev_eui: str,
        payload: dict,
        event: ChirpStackEvent,
    ) -> ChirpStackHandleResult:
        self.process_result.event = event
        return self.process_result

    async def _get_event(self, event_id: int) -> ChirpStackEvent | None:
        return self.db.last_event


class ChirpStackEventServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fport_20_does_not_create_location(self) -> None:
        service = RoutingEventService(self._build_device(), self._build_up_event("AQABAQA=", 20))
        event = self._build_event()

        with patch("src.integrations.chirpstack.service.decode_up_event", side_effect=AssertionError("location path should not run")):
            with patch.object(
                service,
                "_process_application_ack_up_event",
                AsyncMock(
                    return_value=ChirpStackHandleResult(
                        success=True,
                        processed_kind="command_ack",
                        device_id=26,
                    )
                ),
            ):
                result = await service._process_up_event("app", "0102030405060708", {}, event)

        self.assertEqual(result.processed_kind, "command_ack")

    async def test_fport_20_command_seq_not_found_marks_event_unprocessed(self) -> None:
        service = RoutingEventService(self._build_device(), self._build_up_event("AQArAQA=", 20))
        event = self._build_event()

        with patch(
            "src.integrations.chirpstack.service.DeviceCommandAckService.process_ack_by_command_seq",
            AsyncMock(
                return_value=DeviceCommandAckResult(
                    success=False,
                    failure_reason="COMMAND_ACK_COMMAND_SEQ_NOT_FOUND",
                )
            ),
        ):
            result = await service._process_application_ack_up_event(service.device, service.up_event, event)

        self.assertFalse(result.success)
        self.assertFalse(event.processed)
        self.assertEqual(event.error_message, "COMMAND_ACK_COMMAND_SEQ_NOT_FOUND")

    async def test_fport_10_location_creates_location(self) -> None:
        service = RoutingEventService(self._build_device(), self._build_up_event(self._location_base64(), 10))
        event = self._build_event()
        location_stub = self._build_location_stub()

        with patch(
            "src.integrations.chirpstack.service.decode_up_event",
            return_value=NormalizedTelemetry(
                device_timestamp=None,
                latitude=-33.3012,
                longitude=-66.3371,
                altitude=520.0,
                accuracy=5.0,
            ),
        ):
            with patch(
                "src.integrations.chirpstack.service.LocationIngestionService.persist_location",
                AsyncMock(return_value=location_stub),
            ) as persist_location:
                result = await service._process_up_event("app", "0102030405060708", {}, event)

        self.assertEqual(result.processed_kind, "location")
        self.assertEqual(result.location_id, 77)
        self.assertIsNotNone(result.realtime_location_data)
        self.assertEqual(result.realtime_location_data.client_id, 4)
        self.assertEqual(
            result.realtime_location_data.recorded_at.isoformat(),
            "2026-07-13T12:00:00+00:00",
        )
        persist_location.assert_awaited_once()

    async def test_fport_10_location_uses_asset_client_id_when_device_client_missing(self) -> None:
        service = RoutingEventService(
            self._build_device(client_id=None, asset_id=9),
            self._build_up_event(self._location_base64(), 10),
        )
        service.db.asset_client_id_by_asset_id[9] = 12
        event = self._build_event()

        with patch(
            "src.integrations.chirpstack.service.decode_up_event",
            return_value=NormalizedTelemetry(
                device_timestamp=None,
                latitude=-33.3012,
                longitude=-66.3371,
                altitude=520.0,
                accuracy=5.0,
            ),
        ):
            with patch(
                "src.integrations.chirpstack.service.LocationIngestionService.persist_location",
                AsyncMock(return_value=self._build_location_stub(device_timestamp=None)),
            ):
                result = await service._process_up_event("app", "0102030405060708", {}, event)

        self.assertIsNotNone(result.realtime_location_data)
        self.assertEqual(result.realtime_location_data.client_id, 12)
        self.assertEqual(
            result.realtime_location_data.recorded_at.isoformat(),
            "2026-07-13T12:05:00+00:00",
        )

    async def test_fport_10_rejects_application_id_mismatch(self) -> None:
        service = RoutingEventService(
            self._build_device(chirpstack_application_id="expected-app"),
            self._build_up_event(self._location_base64(), 10),
        )
        event = self._build_event(application_id="wrong-app")

        with patch(
            "src.integrations.chirpstack.service.LocationIngestionService.persist_location",
            AsyncMock(),
        ) as persist_location:
            result = await service._process_up_event(
                "wrong-app",
                "0102030405060708",
                {},
                event,
            )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "APPLICATION_ID_MISMATCH")
        self.assertFalse(event.processed)
        persist_location.assert_not_awaited()

    async def test_fport_10_rejects_missing_device_application_id(self) -> None:
        service = RoutingEventService(
            self._build_device(chirpstack_application_id=None),
            self._build_up_event(self._location_base64(), 10),
        )
        event = self._build_event()

        with patch(
            "src.integrations.chirpstack.service.LocationIngestionService.persist_location",
            AsyncMock(),
        ) as persist_location:
            result = await service._process_up_event(
                "app",
                "0102030405060708",
                {},
                event,
            )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "DEVICE_APPLICATION_ID_MISSING")
        self.assertFalse(event.processed)
        persist_location.assert_not_awaited()

    async def test_fport_11_status_does_not_create_location(self) -> None:
        service = RoutingEventService(self._build_device(), self._build_up_event("AQJXDnQBAQI=", 11))
        event = self._build_event()

        with patch("src.integrations.chirpstack.service.decode_up_event", side_effect=AssertionError("location path should not run")):
            result = await service._process_up_event("app", "0102030405060708", {}, event)

        self.assertEqual(result.processed_kind, "status")
        self.assertTrue(event.processed)

    async def test_handle_event_publishes_location_after_final_commit(self) -> None:
        db = FakeSession()
        service = HandleEventService(db, self._build_location_handle_result())
        publish_calls = []

        async def publish_stub(**kwargs):
            self.assertEqual(db.commit_count, 2)
            publish_calls.append(kwargs)
            return 3

        with patch("src.integrations.chirpstack.service.publish_location_updated", new=publish_stub):
            result = await service.handle_event(
                "application/app/device/0102030405060708/event/up",
                {"deduplicationId": "dedup-1"},
            )

        self.assertTrue(result.success)
        self.assertEqual(db.commit_count, 2)
        self.assertEqual(len(publish_calls), 1)
        self.assertEqual(publish_calls[0]["location_id"], 77)
        self.assertEqual(publish_calls[0]["client_id"], 4)

    async def test_handle_event_continues_when_redis_publish_fails(self) -> None:
        db = FakeSession()
        service = HandleEventService(db, self._build_location_handle_result())

        with patch(
            "src.integrations.chirpstack.service.publish_location_updated",
            new=AsyncMock(side_effect=RedisError("redis unavailable")),
        ) as publish_location_updated:
            result = await service.handle_event(
                "application/app/device/0102030405060708/event/up",
                {"deduplicationId": "dedup-2"},
            )

        self.assertTrue(result.success)
        self.assertEqual(db.commit_count, 2)
        self.assertEqual(db.rollback_count, 0)
        publish_location_updated.assert_awaited_once()

    async def test_handle_event_does_not_publish_when_final_commit_fails(self) -> None:
        db = FakeSession(commit_side_effects=[None, RuntimeError("final commit failed"), None])
        service = HandleEventService(db, self._build_location_handle_result())

        with patch(
            "src.integrations.chirpstack.service.publish_location_updated",
            new=AsyncMock(),
        ) as publish_location_updated:
            result = await service.handle_event(
                "application/app/device/0102030405060708/event/up",
                {"deduplicationId": "dedup-3"},
            )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "final commit failed")
        self.assertEqual(db.rollback_count, 1)
        self.assertEqual(db.commit_count, 3)
        self.assertEqual(db.last_event.error_message, "final commit failed")
        publish_location_updated.assert_not_awaited()

    async def test_txack_rejects_application_id_mismatch(self) -> None:
        service = RoutingEventService(self._build_device(chirpstack_application_id="expected-app"), None)
        event = self._build_event(event_type="txack", application_id="wrong-app")

        with patch(
            "src.integrations.chirpstack.service.ChirpStackTxAckEvent.model_validate",
            side_effect=AssertionError("txack payload should not be parsed"),
        ):
            result = await service._process_txack_event(
                "wrong-app",
                "0102030405060708",
                {},
                event,
            )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "APPLICATION_ID_MISMATCH")
        self.assertFalse(event.processed)

    async def test_ack_rejects_application_id_mismatch(self) -> None:
        service = RoutingEventService(self._build_device(chirpstack_application_id="expected-app"), None)
        event = self._build_event(event_type="ack", application_id="wrong-app")

        with patch(
            "src.integrations.chirpstack.service.ChirpStackNetworkAckEvent.model_validate",
            side_effect=AssertionError("ack payload should not be parsed"),
        ):
            result = await service._process_network_ack_event(
                "wrong-app",
                "0102030405060708",
                {},
                event,
            )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "APPLICATION_ID_MISMATCH")
        self.assertFalse(event.processed)

    def _build_device(
        self,
        chirpstack_application_id: str | None = "app",
        client_id: int | None = 4,
        asset_id: int | None = None,
    ) -> Device:
        return Device(
            id_device=26,
            serial="COLLAR-026",
            name="Collar 026",
            type="COLLAR",
            active=True,
            deleted="N",
            state=DeviceState.ON,
            communication_protocol=DeviceCommunicationProtocol.CHIRPSTACK,
            chirpstack_dev_eui="0102030405060708",
            chirpstack_application_id=chirpstack_application_id,
            client_id=client_id,
            asset_id=asset_id,
        )

    def _build_event(self, event_type: str = "up", application_id: str = "app") -> ChirpStackEvent:
        return ChirpStackEvent(
            event_type=event_type,
            application_id=application_id,
            dev_eui="0102030405060708",
            topic=f"application/{application_id}/device/0102030405060708/event/{event_type}",
            payload={},
            processed=False,
            error_message=None,
        )

    def _build_up_event(self, data_base64: str, f_port: int):
        from src.integrations.chirpstack.schemas import ChirpStackUpEvent

        return ChirpStackUpEvent.model_validate(
            {
                "time": "2026-07-13T12:00:00Z",
                "deviceInfo": {
                    "devEui": "0102030405060708",
                    "deviceName": "Collar 026",
                    "deviceProfileId": "profile-1",
                },
                "fPort": f_port,
                "data": data_base64,
                "rxInfo": [],
            }
        )

    def _location_base64(self) -> str:
        return base64.b64encode(bytes.fromhex("01 01 EC 27 D6 E0 D8 70 44 70 02 08 05 57 01")).decode("ascii")

    def _build_location_stub(
        self,
        *,
        device_timestamp: datetime | None = datetime(2026, 7, 13, 12, 0, 0),
        received_at: datetime = datetime(2026, 7, 13, 12, 5, 0),
    ):
        return type(
            "LocationStub",
            (),
            {
                "id_location": 77,
                "latitude": -33.3012,
                "longitude": -66.3371,
                "altitude": 520.0,
                "accuracy": 5.0,
                "device_timestamp": device_timestamp,
                "received_at": received_at,
            },
        )()

    def _build_location_handle_result(self) -> ChirpStackHandleResult:
        return ChirpStackHandleResult(
            success=True,
            processed_kind="location",
            device_id=26,
            location_id=77,
            realtime_location_data=RealtimeLocationData(
                location_id=77,
                client_id=4,
                device_id=26,
                device_serial="COLLAR-026",
                latitude=-33.3012,
                longitude=-66.3371,
                altitude=520.0,
                accuracy=5.0,
                recorded_at=datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC),
            ),
        )


if __name__ == "__main__":
    unittest.main()
