import base64
import unittest

from src.integrations.chirpstack.downlink_encoder import encode_command_downlink
from src.integrations.chirpstack.payload_codec import (
    decode_command_ack_payload_v1,
    decode_location_payload_v1,
    decode_status_payload_v1,
)
from src.models.device_command import DeviceCommandType
from src.schemas.device_command_ack import DeviceCommandAckStatus


class ChirpStackBinaryContractTests(unittest.TestCase):
    def test_encode_set_report_interval(self) -> None:
        encoded = encode_command_downlink(
            command_uuid="cmd-1",
            command_seq=42,
            command_type=DeviceCommandType.SET_REPORT_INTERVAL,
            payload_fields={"interval_seconds": 60},
        )
        self.assertEqual(encoded.data.hex(" ").upper(), "01 01 00 2A 00 00 3C")

    def test_encode_warning_sound(self) -> None:
        encoded = encode_command_downlink(
            command_uuid="cmd-2",
            command_seq=43,
            command_type=DeviceCommandType.WARNING_SOUND,
            payload_fields={"duration_seconds": 5},
        )
        self.assertEqual(encoded.data.hex(" ").upper(), "01 02 00 2B 00 05")

    def test_encode_stop_correction(self) -> None:
        encoded = encode_command_downlink(
            command_uuid="cmd-3",
            command_seq=44,
            command_type=DeviceCommandType.STOP_CORRECTION,
            payload_fields={},
        )
        self.assertEqual(encoded.data.hex(" ").upper(), "01 03 00 2C 00")

    def test_encode_request_status(self) -> None:
        encoded = encode_command_downlink(
            command_uuid="cmd-4",
            command_seq=45,
            command_type=DeviceCommandType.REQUEST_STATUS,
            payload_fields={},
        )
        self.assertEqual(encoded.data.hex(" ").upper(), "01 04 00 2D 00")

    def test_encode_rejects_command_seq_zero(self) -> None:
        with self.assertRaisesRegex(ValueError, "command_seq must be between 1 and 65535"):
            encode_command_downlink(
                command_uuid="cmd-5",
                command_seq=0,
                command_type=DeviceCommandType.REQUEST_STATUS,
                payload_fields={},
            )

    def test_encode_rejects_command_seq_above_uint16(self) -> None:
        with self.assertRaisesRegex(ValueError, "command_seq must be between 1 and 65535"):
            encode_command_downlink(
                command_uuid="cmd-6",
                command_seq=65536,
                command_type=DeviceCommandType.REQUEST_STATUS,
                payload_fields={},
            )

    def test_encode_rejects_zero_duration(self) -> None:
        with self.assertRaisesRegex(ValueError, "duration_seconds must be between 1 and 255"):
            encode_command_downlink(
                command_uuid="cmd-7",
                command_seq=1,
                command_type=DeviceCommandType.WARNING_SOUND,
                payload_fields={"duration_seconds": 0},
            )

    def test_encode_rejects_zero_interval(self) -> None:
        with self.assertRaisesRegex(ValueError, "interval_seconds must be between 1 and 65535"):
            encode_command_downlink(
                command_uuid="cmd-8",
                command_seq=1,
                command_type=DeviceCommandType.SET_REPORT_INTERVAL,
                payload_fields={"interval_seconds": 0},
            )

    def test_decode_command_ack_executed(self) -> None:
        payload = decode_command_ack_payload_v1(
            self._build_up_event("AQArAQA=")
        )
        self.assertEqual(payload.command_seq, 43)
        self.assertEqual(payload.status, DeviceCommandAckStatus.EXECUTED)
        self.assertIsNone(payload.error_message)

    def test_decode_command_ack_failed_low_battery(self) -> None:
        payload = decode_command_ack_payload_v1(
            self._build_up_event("AQArAwQ=")
        )
        self.assertEqual(payload.command_seq, 43)
        self.assertEqual(payload.status, DeviceCommandAckStatus.FAILED)
        self.assertEqual(payload.error_message, "LOW_BATTERY")

    def test_decode_command_ack_rejects_invalid_length(self) -> None:
        with self.assertRaisesRegex(ValueError, "COMMAND_ACK_INVALID_LENGTH"):
            decode_command_ack_payload_v1(self._build_up_event("AQArAQ=="))

    def test_decode_command_ack_rejects_unknown_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "COMMAND_ACK_UNSUPPORTED_VERSION"):
            decode_command_ack_payload_v1(self._build_up_event("AgArAQA="))

    def test_decode_command_ack_rejects_unknown_status(self) -> None:
        with self.assertRaisesRegex(ValueError, "COMMAND_ACK_UNKNOWN_STATUS"):
            decode_command_ack_payload_v1(self._build_up_event("AQArBgA="))

    def test_decode_location_payload_v1(self) -> None:
        event = self._build_up_event(
            base64.b64encode(bytes.fromhex("01 01 EC 27 D6 E0 D8 70 44 70 02 08 05 57 01")).decode("ascii"),
            f_port=10,
        )
        telemetry = decode_location_payload_v1(event)
        self.assertAlmostEqual(telemetry.latitude, -33.2933408, places=4)
        self.assertAlmostEqual(telemetry.longitude, -66.3731088, places=4)
        self.assertEqual(telemetry.extra["gps_fix_label"], "GPS_FIX")

    def test_decode_status_payload_v1(self) -> None:
        event = self._build_up_event(
            base64.b64encode(bytes.fromhex("01 02 57 0E 74 01 01 02")).decode("ascii"),
            f_port=11,
        )
        status = decode_status_payload_v1(event)
        self.assertEqual(status.battery_percent, 87)
        self.assertEqual(status.battery_mv, 3700)
        self.assertEqual(status.device_state, "SAFE")
        self.assertEqual(status.gps_fix_type, "GPS_FIX")
        self.assertEqual(status.active_error_flags, ["LOW_BATTERY"])

    def _build_up_event(self, data_base64: str, f_port: int = 20):
        from src.integrations.chirpstack.schemas import ChirpStackUpEvent

        return ChirpStackUpEvent.model_validate(
            {
                "time": "2026-07-13T12:00:00Z",
                "deviceInfo": {"devEui": "0102030405060708", "deviceName": "Collar"},
                "fPort": f_port,
                "data": data_base64,
                "rxInfo": [],
            }
        )


if __name__ == "__main__":
    unittest.main()
