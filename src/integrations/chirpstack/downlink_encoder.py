import math
import struct
from dataclasses import dataclass
from typing import Any

from src.integrations.chirpstack.binary_contract import (
    COMMAND_FPORT,
    COMMAND_TYPE_REQUEST_STATUS,
    COMMAND_TYPE_SET_REPORT_INTERVAL,
    COMMAND_TYPE_STOP_CORRECTION,
    COMMAND_TYPE_WARNING_SOUND,
    PROTOCOL_VERSION_V1,
)
from src.models.device_command import DeviceCommandType


@dataclass(slots=True, frozen=True)
class EncodedChirpStackDownlink:
    command_id: str
    command_seq: int
    command_type: DeviceCommandType
    f_port: int
    data: bytes
    confirmed: bool


@dataclass(slots=True, frozen=True)
class DecodedChirpStackCommandDownlink:
    protocol_version: int
    command_type: DeviceCommandType
    command_seq: int
    flags: int
    payload_fields: dict[str, int]


def encode_command_downlink(
    command_uuid: str,
    command_seq: int,
    command_type: DeviceCommandType,
    payload_fields: dict[str, Any] | None = None,
) -> EncodedChirpStackDownlink:
    payload_fields = payload_fields or {}
    _validate_command_seq(command_seq)
    flags = _normalize_flags(payload_fields.get("flags", 0))
    data = _encode_command_payload(
        command_type=command_type,
        command_seq=command_seq,
        flags=flags,
        payload_fields=payload_fields,
    )

    return EncodedChirpStackDownlink(
        command_id=command_uuid,
        command_seq=command_seq,
        command_type=command_type,
        f_port=COMMAND_FPORT,
        data=data,
        confirmed=True,
    )


def decode_command_downlink_payload_v1(data: bytes) -> DecodedChirpStackCommandDownlink:
    if len(data) < 5:
        raise ValueError("Invalid COMMAND payload length")

    protocol_version, command_type_code, command_seq, flags = struct.unpack(">BBHB", data[:5])
    if protocol_version != PROTOCOL_VERSION_V1:
        raise ValueError(f"Unsupported COMMAND protocol version: {protocol_version}")

    _validate_command_seq(command_seq)
    command_type = _command_type_from_code(command_type_code)
    payload_fields = _decode_command_specific_payload(command_type, data[5:])
    return DecodedChirpStackCommandDownlink(
        protocol_version=protocol_version,
        command_type=command_type,
        command_seq=command_seq,
        flags=flags,
        payload_fields=payload_fields,
    )


def _encode_command_payload(
    command_type: DeviceCommandType,
    command_seq: int,
    flags: int,
    payload_fields: dict[str, Any],
) -> bytes:
    command_type_code = _command_type_to_code(command_type)
    if command_type == DeviceCommandType.SET_REPORT_INTERVAL:
        interval_seconds = _normalize_interval_seconds(payload_fields)
        return struct.pack(
            ">BBHBH",
            PROTOCOL_VERSION_V1,
            command_type_code,
            command_seq,
            flags,
            interval_seconds,
        )

    if command_type == DeviceCommandType.WARNING_SOUND:
        duration_seconds = _normalize_duration_seconds(payload_fields)
        return struct.pack(
            ">BBHBB",
            PROTOCOL_VERSION_V1,
            command_type_code,
            command_seq,
            flags,
            duration_seconds,
        )

    if command_type in {
        DeviceCommandType.STOP_CORRECTION,
        DeviceCommandType.REQUEST_STATUS,
    }:
        return struct.pack(
            ">BBHB",
            PROTOCOL_VERSION_V1,
            command_type_code,
            command_seq,
            flags,
        )

    raise ValueError(f"Unsupported ChirpStack binary command type: {command_type.value}")


def _decode_command_specific_payload(
    command_type: DeviceCommandType,
    payload: bytes,
) -> dict[str, int]:
    if command_type == DeviceCommandType.SET_REPORT_INTERVAL:
        if len(payload) != 2:
            raise ValueError("Invalid SET_REPORT_INTERVAL payload length")
        return {"interval_seconds": struct.unpack(">H", payload)[0]}

    if command_type == DeviceCommandType.WARNING_SOUND:
        if len(payload) != 1:
            raise ValueError("Invalid WARNING_SOUND payload length")
        return {"duration_seconds": payload[0]}

    if command_type in {
        DeviceCommandType.STOP_CORRECTION,
        DeviceCommandType.REQUEST_STATUS,
    }:
        if payload:
            raise ValueError(f"Invalid {command_type.value} payload length")
        return {}

    raise ValueError(f"Unsupported ChirpStack binary command type: {command_type.value}")


def _command_type_to_code(command_type: DeviceCommandType) -> int:
    mapping = {
        DeviceCommandType.SET_REPORT_INTERVAL: COMMAND_TYPE_SET_REPORT_INTERVAL,
        DeviceCommandType.WARNING_SOUND: COMMAND_TYPE_WARNING_SOUND,
        DeviceCommandType.STOP_CORRECTION: COMMAND_TYPE_STOP_CORRECTION,
        DeviceCommandType.REQUEST_STATUS: COMMAND_TYPE_REQUEST_STATUS,
    }
    try:
        return mapping[command_type]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported ChirpStack binary command type: {command_type.value}"
        ) from exc


def _command_type_from_code(command_type_code: int) -> DeviceCommandType:
    mapping = {
        COMMAND_TYPE_SET_REPORT_INTERVAL: DeviceCommandType.SET_REPORT_INTERVAL,
        COMMAND_TYPE_WARNING_SOUND: DeviceCommandType.WARNING_SOUND,
        COMMAND_TYPE_STOP_CORRECTION: DeviceCommandType.STOP_CORRECTION,
        COMMAND_TYPE_REQUEST_STATUS: DeviceCommandType.REQUEST_STATUS,
    }
    command_type = mapping.get(command_type_code)
    if command_type is None:
        raise ValueError(f"Unsupported COMMAND type code: {command_type_code}")
    return command_type


def _normalize_interval_seconds(payload_fields: dict[str, Any]) -> int:
    interval_seconds = payload_fields.get("interval_seconds")
    if interval_seconds is None:
        raise ValueError("SET_REPORT_INTERVAL requires interval_seconds")

    interval_seconds = int(interval_seconds)
    if interval_seconds < 1 or interval_seconds > 65535:
        raise ValueError("interval_seconds must be between 1 and 65535")
    return interval_seconds


def _normalize_duration_seconds(payload_fields: dict[str, Any]) -> int:
    duration_seconds = payload_fields.get("duration_seconds")
    if duration_seconds is None and "duration_ms" in payload_fields:
        duration_seconds = max(1, math.ceil(int(payload_fields["duration_ms"]) / 1000))

    if duration_seconds is None:
        raise ValueError("WARNING_SOUND requires duration_seconds")

    duration_seconds = int(duration_seconds)
    if duration_seconds < 1 or duration_seconds > 255:
        raise ValueError("duration_seconds must be between 1 and 255")
    return duration_seconds


def _normalize_flags(flags: Any) -> int:
    normalized = int(flags)
    if normalized < 0 or normalized > 255:
        raise ValueError("flags must be between 0 and 255")
    return normalized


def _validate_command_seq(command_seq: int) -> None:
    if command_seq < 1 or command_seq > 65535:
        raise ValueError("command_seq must be between 1 and 65535")
