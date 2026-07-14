import unittest
from datetime import datetime

from src.models.device import Device, DeviceCommunicationProtocol, DeviceState
from src.models.device_command import DeviceCommand, DeviceCommandStatus, DeviceCommandType
from src.schemas.device_command_ack import DeviceCommandAckPayload, DeviceCommandAckStatus
from src.service.device_command_ack_service import DeviceCommandAckService
from src.service.device_command_service import DeviceCommandService
from src.service.device_command_sequence_service import (
    DeviceCommandSequenceError,
    DeviceCommandSequenceService,
)


class FakeSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, value) -> None:
        self.added.append(value)


class StubSequenceService(DeviceCommandSequenceService):
    def __init__(self, last_command_seq: int | None):
        super().__init__(FakeSession())
        self.last_command_seq = last_command_seq
        self.locked_device_id = None

    async def _lock_device(self, device_id: int) -> None:
        self.locked_device_id = device_id

    async def _get_last_command_seq(self, device_id: int) -> int | None:
        return self.last_command_seq


class StubAckService(DeviceCommandAckService):
    def __init__(self, command_by_uuid=None, command_by_seq=None):
        super().__init__(FakeSession())
        self.command_by_uuid = command_by_uuid
        self.command_by_seq = command_by_seq

    async def _get_command_by_uuid(self, command_uuid: str | None):
        return self.command_by_uuid

    async def _get_command_by_device_and_seq(self, device_id: int, command_seq: int):
        return self.command_by_seq


class DeviceCommandSequenceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_command_seq_is_one(self) -> None:
        service = StubSequenceService(last_command_seq=None)
        self.assertEqual(await service.allocate_next_command_seq(26), 1)
        self.assertEqual(service.locked_device_id, 26)

    async def test_next_command_seq_increments(self) -> None:
        service = StubSequenceService(last_command_seq=1)
        self.assertEqual(await service.allocate_next_command_seq(26), 2)

    async def test_command_seq_never_wraps_to_zero_in_v1(self) -> None:
        service = StubSequenceService(last_command_seq=65534)
        self.assertEqual(await service.allocate_next_command_seq(26), 65535)

    async def test_command_seq_exhaustion_is_clear(self) -> None:
        service = StubSequenceService(last_command_seq=65535)
        with self.assertRaises(DeviceCommandSequenceError):
            await service.allocate_next_command_seq(26)


class DeviceCommandAckServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_ack_by_command_seq_marks_acked(self) -> None:
        command = self._build_command(command_seq=43)
        service = StubAckService(command_by_seq=command)

        result = await service.process_ack_by_command_seq(
            26,
            DeviceCommandAckPayload(
                command_seq=43,
                status=DeviceCommandAckStatus.EXECUTED,
                executed_at=datetime(2026, 7, 13, 12, 0, 0),
            ),
        )

        self.assertTrue(result.success)
        self.assertEqual(command.status, DeviceCommandStatus.ACKED)
        self.assertIsNotNone(command.ack_at)

    async def test_process_ack_by_command_seq_returns_not_found(self) -> None:
        service = StubAckService(command_by_seq=None)

        result = await service.process_ack_by_command_seq(
            26,
            DeviceCommandAckPayload(
                command_seq=999,
                status=DeviceCommandAckStatus.EXECUTED,
            ),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "COMMAND_ACK_COMMAND_SEQ_NOT_FOUND")


class DeviceCommandServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_chirpstack_devices_cannot_create_commands(self) -> None:
        service = DeviceCommandService(FakeSession())

        with self.assertRaisesRegex(ValueError, "does not support ChirpStack downlinks"):
            await service.create_pending_command(
                device=Device(
                    id_device=26,
                    serial="MQTT-026",
                    name="MQTT Device",
                    type="COLLAR",
                    active=True,
                    deleted="N",
                    state=DeviceState.ON,
                    communication_protocol=DeviceCommunicationProtocol.MQTT,
                ),
                command_type=DeviceCommandType.REQUEST_STATUS,
                reason="manual_test",
            )

    def _build_command(self, command_seq: int) -> DeviceCommand:
        return DeviceCommand(
            command_uuid="command-uuid",
            command_seq=command_seq,
            device_id=26,
            command_type=DeviceCommandType.REQUEST_STATUS,
            status=DeviceCommandStatus.SENT,
            topic="application/app/device/dev/command/down",
            payload={},
            qos=1,
            retain=False,
        )


if __name__ == "__main__":
    unittest.main()
