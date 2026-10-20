import base64

import pytest

from src.integrations.chirpstack.downlink_encoder import encode_command_downlink
from src.integrations.chirpstack.payload_codec import (
    decode_command_ack_payload_v1,
    decode_location_payload_v1,
    decode_status_payload_v1,
)
from src.models.device_command import DeviceCommandType
from src.schemas.device_command_ack import DeviceCommandAckStatus
from src.integrations.chirpstack.schemas import ChirpStackUpEvent


def build_up_event(data_base64: str, f_port: int = 20) -> ChirpStackUpEvent:
    return ChirpStackUpEvent.model_validate(
        {
            "time": "2026-07-13T12:00:00Z",
            "deviceInfo": {"devEui": "0102030405060708", "deviceName": "Collar"},
            "fPort": f_port,
            "data": data_base64,
            "rxInfo": [],
        }
    )


def test_encode_rejects_zero_duration() -> None:
    with pytest.raises(ValueError, match="duration_seconds must be between 1 and 255"):
        encode_command_downlink(
            command_uuid="cmd-7",
            command_seq=1,
            command_type=DeviceCommandType.WARNING_SOUND,
            payload_fields={"duration_seconds": 0},
        )


def test_encode_rejects_zero_interval() -> None:
    with pytest.raises(ValueError, match="interval_seconds must be between 1 and 65535"):
        encode_command_downlink(
            command_uuid="cmd-8",
            command_seq=1,
            command_type=DeviceCommandType.SET_REPORT_INTERVAL,
            payload_fields={"interval_seconds": 0},
        )


def test_decode_command_ack_executed() -> None:
    payload = decode_command_ack_payload_v1(build_up_event("AQArAQA="))

    assert payload.command_seq == 43
    assert payload.status == DeviceCommandAckStatus.EXECUTED
    assert payload.error_message is None


def test_decode_command_ack_failed_low_battery() -> None:
    payload = decode_command_ack_payload_v1(build_up_event("AQArAwQ="))

    assert payload.command_seq == 43
    assert payload.status == DeviceCommandAckStatus.FAILED
    assert payload.error_message == "LOW_BATTERY"


def test_decode_command_ack_rejects_invalid_length() -> None:
    with pytest.raises(ValueError, match="COMMAND_ACK_INVALID_LENGTH"):
        decode_command_ack_payload_v1(build_up_event("AQArAQ=="))


def test_decode_command_ack_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="COMMAND_ACK_UNSUPPORTED_VERSION"):
        decode_command_ack_payload_v1(build_up_event("AgArAQA="))


def test_decode_command_ack_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="COMMAND_ACK_UNKNOWN_STATUS"):
        decode_command_ack_payload_v1(build_up_event("AQArBgA="))


def test_decode_location_payload_v1() -> None:
    event = build_up_event(
        base64.b64encode(bytes.fromhex("01 01 EC 27 D6 E0 D8 70 44 70 02 08 05 57 01")).decode("ascii"),
        f_port=10,
    )

    telemetry = decode_location_payload_v1(event)

    assert telemetry.latitude == pytest.approx(-33.2933408, abs=0.0001)
    assert telemetry.longitude == pytest.approx(-66.3731088, abs=0.0001)
    assert telemetry.extra["gps_fix_label"] == "GPS_FIX"


def test_decode_status_payload_v1() -> None:
    event = build_up_event(
        base64.b64encode(bytes.fromhex("01 02 57 0E 74 01 01 02")).decode("ascii"),
        f_port=11,
    )

    status = decode_status_payload_v1(event)

    assert status.battery_percent == 87
    assert status.battery_mv == 3700
    assert status.device_state == "SAFE"
    assert status.gps_fix_type == "GPS_FIX"
    assert status.active_error_flags == ["LOW_BATTERY"]


@pytest.mark.parametrize(
    ("command_uuid", "command_seq", "command_type", "payload_fields", "expected_hex"),
    [
        pytest.param(
            "cmd-1",
            42,
            DeviceCommandType.SET_REPORT_INTERVAL,
            {"interval_seconds": 60},
            "01 01 00 2A 00 00 3C",
            id="set-report-interval",
        ),
        pytest.param(
            "cmd-2",
            43,
            DeviceCommandType.WARNING_SOUND,
            {"duration_seconds": 5},
            "01 02 00 2B 00 05",
            id="warning-sound",
        ),
        pytest.param(
            "cmd-3",
            44,
            DeviceCommandType.STOP_CORRECTION,
            {},
            "01 03 00 2C 00",
            id="stop-correction",
        ),
        pytest.param(
            "cmd-4",
            45,
            DeviceCommandType.REQUEST_STATUS,
            {},
            "01 04 00 2D 00",
            id="request-status",
        ),
    ],
)
def test_encode_supported_commands(
    command_uuid: str,
    command_seq: int,
    command_type: DeviceCommandType,
    payload_fields: dict[str, int],
    expected_hex: str,
) -> None:
    encoded = encode_command_downlink(
        command_uuid=command_uuid,
        command_seq=command_seq,
        command_type=command_type,
        payload_fields=payload_fields,
    )

    assert encoded.data.hex(" ").upper() == expected_hex


@pytest.mark.parametrize(
    "command_seq",
    [0, 65536],
    ids=["zero", "above-uint16"],
)
def test_encode_rejects_command_seq_outside_uint16_range(command_seq: int) -> None:
    with pytest.raises(
        ValueError,
        match="command_seq must be between 1 and 65535",
    ):
        encode_command_downlink(
            command_uuid=f"cmd-{command_seq}",
            command_seq=command_seq,
            command_type=DeviceCommandType.REQUEST_STATUS,
            payload_fields={},
        )
