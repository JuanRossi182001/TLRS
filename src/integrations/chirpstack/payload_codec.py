import base64
import binascii
import struct
from dataclasses import dataclass
from datetime import datetime, timezone

from src.application.telemetry.normalized_telemetry import NormalizedTelemetry
from src.integrations.chirpstack.binary_contract import (
    COMMAND_ACK_ERROR_BUSY,
    COMMAND_ACK_ERROR_COMMAND_EXPIRED_ON_DEVICE,
    COMMAND_ACK_ERROR_HARDWARE_ERROR,
    COMMAND_ACK_ERROR_INVALID_PAYLOAD,
    COMMAND_ACK_ERROR_LOW_BATTERY,
    COMMAND_ACK_ERROR_NO_ERROR,
    COMMAND_ACK_ERROR_UNKNOWN_COMMAND_TYPE,
    COMMAND_ACK_PAYLOAD_LENGTH_V1,
    COMMAND_ACK_STATUS_DUPLICATE,
    COMMAND_ACK_STATUS_EXECUTED,
    COMMAND_ACK_STATUS_EXPIRED,
    COMMAND_ACK_STATUS_FAILED,
    COMMAND_ACK_STATUS_REJECTED,
    GPS_FIX_DGPS,
    GPS_FIX_ESTIMATED,
    GPS_FIX_GPS,
    GPS_FIX_NO_FIX,
    LOCATION_MESSAGE_TYPE,
    LOCATION_PAYLOAD_LENGTH_V1,
    PROTOCOL_VERSION_V1,
    STATUS_MESSAGE_TYPE,
    STATUS_PAYLOAD_LENGTH_V1,
)
from src.integrations.chirpstack.schemas import ChirpStackUpEvent
from src.schemas.device_command_ack import DeviceCommandAckPayload, DeviceCommandAckStatus


class ChirpStackPayloadDecodeError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class DecodedChirpStackStatusPayload:
    battery_percent: int
    battery_mv: int
    device_state_code: int
    device_state: str
    gps_fix_type_code: int
    gps_fix_type: str
    error_flags: int
    active_error_flags: list[str]


def decode_location_payload_v1(event: ChirpStackUpEvent) -> NormalizedTelemetry:
    payload = _decode_base64_data(event.data)
    if len(payload) != LOCATION_PAYLOAD_LENGTH_V1:
        raise ChirpStackPayloadDecodeError(
            "Invalid ChirpStack location payload length: "
            f"expected {LOCATION_PAYLOAD_LENGTH_V1}, got {len(payload)}"
        )

    version, message_type, lat_e7, lng_e7, altitude_meters, accuracy_meters, battery_percent, gps_fix_type = struct.unpack(
        ">BBiihBBB",
        payload,
    )

    if version != PROTOCOL_VERSION_V1:
        raise ChirpStackPayloadDecodeError(
            f"Unsupported ChirpStack location payload version: {version}"
        )

    if message_type != LOCATION_MESSAGE_TYPE:
        raise ChirpStackPayloadDecodeError(
            f"Unsupported ChirpStack location message type: {message_type}"
        )

    latitude = lat_e7 / 10_000_000
    longitude = lng_e7 / 10_000_000
    _validate_coordinates(latitude, longitude)

    gps_fix_label = _decode_gps_fix_type(gps_fix_type)
    accuracy = float(accuracy_meters)
    if gps_fix_type == GPS_FIX_NO_FIX:
        # Reuse the existing GPS_UNCERTAIN path by forcing a clearly unreliable accuracy.
        accuracy = max(accuracy, 255.0)

    battery_value = float(battery_percent)

    return NormalizedTelemetry(
        device_timestamp=_to_utc_naive(event.time),
        latitude=latitude,
        longitude=longitude,
        altitude=float(altitude_meters),
        accuracy=accuracy,
        extra={
            "battery": battery_value,
            "f_port": event.fPort,
            "gateway_ids": [item.gatewayId for item in event.rxInfo if item.gatewayId],
            "device_name": event.deviceInfo.deviceName,
            "serial": event.deviceInfo.tags.get("serial"),
            "payload_format": "chirpstack_binary_v1",
            "message_type": message_type,
            "gps_fix_type": gps_fix_type,
            "gps_fix_label": gps_fix_label,
        },
    )


def decode_status_payload_v1(event: ChirpStackUpEvent) -> DecodedChirpStackStatusPayload:
    payload = _decode_base64_data(event.data)
    if len(payload) != STATUS_PAYLOAD_LENGTH_V1:
        raise ChirpStackPayloadDecodeError(
            "Invalid ChirpStack status payload length: "
            f"expected {STATUS_PAYLOAD_LENGTH_V1}, got {len(payload)}"
        )

    version, message_type, battery_percent, battery_mv, device_state_code, gps_fix_type_code, error_flags = struct.unpack(
        ">BBBHBBB",
        payload,
    )
    if version != PROTOCOL_VERSION_V1:
        raise ChirpStackPayloadDecodeError(
            f"Unsupported ChirpStack status payload version: {version}"
        )
    if message_type != STATUS_MESSAGE_TYPE:
        raise ChirpStackPayloadDecodeError(
            f"Unsupported ChirpStack status message type: {message_type}"
        )

    return DecodedChirpStackStatusPayload(
        battery_percent=battery_percent,
        battery_mv=battery_mv,
        device_state_code=device_state_code,
        device_state=_decode_status_device_state(device_state_code),
        gps_fix_type_code=gps_fix_type_code,
        gps_fix_type=_decode_gps_fix_type(gps_fix_type_code),
        error_flags=error_flags,
        active_error_flags=_decode_status_error_flags(error_flags),
    )


def decode_command_ack_payload_v1(event: ChirpStackUpEvent) -> DeviceCommandAckPayload:
    payload = _decode_base64_data(event.data)
    if len(payload) != COMMAND_ACK_PAYLOAD_LENGTH_V1:
        raise ChirpStackPayloadDecodeError("COMMAND_ACK_INVALID_LENGTH")

    version, command_seq, status_code, error_code = struct.unpack(">BHBB", payload)

    if version != PROTOCOL_VERSION_V1:
        raise ChirpStackPayloadDecodeError("COMMAND_ACK_UNSUPPORTED_VERSION")
    if command_seq == 0:
        raise ChirpStackPayloadDecodeError("COMMAND_ACK_INVALID_COMMAND_SEQ")

    status = _decode_ack_status(status_code)
    error_message = _decode_ack_error(error_code, status)

    return DeviceCommandAckPayload(
        command_seq=command_seq,
        status=status,
        executed_at=event.time,
        error_message=error_message,
    )


def _decode_base64_data(data: str | None) -> bytes:
    if not data:
        raise ChirpStackPayloadDecodeError("Missing data payload in ChirpStack up event")

    try:
        return base64.b64decode(data.encode("ascii"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ChirpStackPayloadDecodeError("Invalid base64 data in ChirpStack up event") from exc


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if latitude < -90 or latitude > 90:
        raise ChirpStackPayloadDecodeError("Latitude out of range")

    if longitude < -180 or longitude > 180:
        raise ChirpStackPayloadDecodeError("Longitude out of range")


def _decode_ack_status(status_code: int) -> DeviceCommandAckStatus:
    mapping = {
        COMMAND_ACK_STATUS_EXECUTED: DeviceCommandAckStatus.EXECUTED,
        COMMAND_ACK_STATUS_REJECTED: DeviceCommandAckStatus.REJECTED,
        COMMAND_ACK_STATUS_FAILED: DeviceCommandAckStatus.FAILED,
        COMMAND_ACK_STATUS_EXPIRED: DeviceCommandAckStatus.EXPIRED,
        COMMAND_ACK_STATUS_DUPLICATE: DeviceCommandAckStatus.DUPLICATE,
    }
    status = mapping.get(status_code)
    if status is None:
        raise ChirpStackPayloadDecodeError("COMMAND_ACK_UNKNOWN_STATUS")
    return status


def _decode_ack_error(
    error_code: int,
    status: DeviceCommandAckStatus,
) -> str | None:
    if error_code == COMMAND_ACK_ERROR_NO_ERROR:
        return None

    mapping = {
        COMMAND_ACK_ERROR_UNKNOWN_COMMAND_TYPE: "UNKNOWN_COMMAND_TYPE",
        COMMAND_ACK_ERROR_INVALID_PAYLOAD: "INVALID_PAYLOAD",
        COMMAND_ACK_ERROR_BUSY: "BUSY",
        COMMAND_ACK_ERROR_LOW_BATTERY: "LOW_BATTERY",
        COMMAND_ACK_ERROR_HARDWARE_ERROR: "HARDWARE_ERROR",
        COMMAND_ACK_ERROR_COMMAND_EXPIRED_ON_DEVICE: "COMMAND_EXPIRED_ON_DEVICE",
    }
    return mapping.get(error_code, f"UNKNOWN_DEVICE_ERROR_CODE_{error_code}_{status.value}")


def _decode_gps_fix_type(gps_fix_type: int) -> str:
    mapping = {
        GPS_FIX_NO_FIX: "NO_FIX",
        GPS_FIX_GPS: "GPS_FIX",
        GPS_FIX_DGPS: "DGPS_FIX",
        GPS_FIX_ESTIMATED: "ESTIMATED",
    }
    try:
        return mapping[gps_fix_type]
    except KeyError as exc:
        raise ChirpStackPayloadDecodeError(
            f"Unsupported ChirpStack gps_fix_type: {gps_fix_type}"
        ) from exc


def _decode_status_device_state(device_state_code: int) -> str:
    mapping = {
        0x00: "UNKNOWN",
        0x01: "SAFE",
        0x02: "NEAR_LIMIT",
        0x03: "OUTSIDE",
        0x04: "GPS_UNCERTAIN",
        0x05: "LOW_BATTERY",
    }
    try:
        return mapping[device_state_code]
    except KeyError as exc:
        raise ChirpStackPayloadDecodeError(
            f"Unsupported ChirpStack status device_state: {device_state_code}"
        ) from exc


def _decode_status_error_flags(error_flags: int) -> list[str]:
    mapping = {
        0: "GPS_ERROR",
        1: "LOW_BATTERY",
        2: "SENSOR_ERROR",
        3: "COMMAND_ERROR",
    }
    active_flags: list[str] = []
    for bit_position, label in mapping.items():
        if error_flags & (1 << bit_position):
            active_flags.append(label)
    return active_flags


def _to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value

    return value.astimezone(timezone.utc).replace(tzinfo=None)
