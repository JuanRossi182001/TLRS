import base64
import unittest
from unittest.mock import AsyncMock, patch

from src.application.telemetry.normalized_telemetry import NormalizedTelemetry
from src.integrations.chirpstack.service import ChirpStackEventService, ChirpStackHandleResult
from src.models.chirpstack_event import ChirpStackEvent
from src.models.device import Device, DeviceCommunicationProtocol, DeviceState
from src.models.device_command import DeviceCommandStatus
from src.service.device_command_ack_service import DeviceCommandAckResult


class FakeSession:
    def add(self, value) -> None:
        return None


class RoutingEventService(ChirpStackEventService):
    def __init__(self, device, up_event):
        super().__init__(FakeSession())
        self.device = device
        self.up_event = up_event

    async def _get_device(self, dev_eui: str):
        return self.device

    def _validate_up_event(self, payload: dict, dev_eui: str):
        return self.up_event


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
                AsyncMock(return_value=type("LocationStub", (), {"id_location": 77})()),
            ) as persist_location:
                result = await service._process_up_event("app", "0102030405060708", {}, event)

        self.assertEqual(result.processed_kind, "location")
        self.assertEqual(result.location_id, 77)
        persist_location.assert_awaited_once()

    async def test_fport_11_status_does_not_create_location(self) -> None:
        service = RoutingEventService(self._build_device(), self._build_up_event("AQJXDnQBAQI=", 11))
        event = self._build_event()

        with patch("src.integrations.chirpstack.service.decode_up_event", side_effect=AssertionError("location path should not run")):
            result = await service._process_up_event("app", "0102030405060708", {}, event)

        self.assertEqual(result.processed_kind, "status")
        self.assertTrue(event.processed)

    def _build_device(self) -> Device:
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
            chirpstack_application_id="app",
        )

    def _build_event(self) -> ChirpStackEvent:
        return ChirpStackEvent(
            event_type="up",
            application_id="app",
            dev_eui="0102030405060708",
            topic="application/app/device/0102030405060708/event/up",
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


if __name__ == "__main__":
    unittest.main()
