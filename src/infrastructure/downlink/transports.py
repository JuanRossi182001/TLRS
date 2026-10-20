from __future__ import annotations

import base64
from dataclasses import dataclass

from src.integrations.chirpstack.api_client import (
    ChirpStackApiClient,
    ChirpStackApiError,
)
from src.integrations.chirpstack.mqtt_topics import is_chirpstack_downlink_topic
from src.models.device_command import DeviceCommand


@dataclass(slots=True)
class DownlinkEnqueueResult:
    sent: bool
    queue_item_id: str | None
    transport: str
    error_message: str | None
    retryable: bool = False


class DownlinkTransport:
    def enqueue(self, command: DeviceCommand) -> DownlinkEnqueueResult:
        raise NotImplementedError


class ChirpStackGrpcDownlinkTransport(DownlinkTransport):
    def __init__(self, api_client: ChirpStackApiClient | None = None):
        self.api_client = api_client or ChirpStackApiClient()

    def enqueue(self, command: DeviceCommand) -> DownlinkEnqueueResult:
        try:
            payload = self._validate_payload(command)
            queue_item_id = self.api_client.enqueue_downlink(
                dev_eui=str(payload["devEui"]),
                f_port=int(payload["fPort"]),
                data=self._decode_data(str(payload["data"])),
                confirmed=bool(payload.get("confirmed", False)),
                expires_at=command.expires_at,
            )
        except ChirpStackApiError as exc:
            return DownlinkEnqueueResult(
                sent=False,
                queue_item_id=None,
                transport="grpc",
                error_message=str(exc),
                retryable=exc.retryable,
            )
        except (TypeError, ValueError) as exc:
            return DownlinkEnqueueResult(
                sent=False,
                queue_item_id=None,
                transport="grpc",
                error_message=f"Invalid ChirpStack downlink payload: {exc}",
                retryable=False,
            )

        return DownlinkEnqueueResult(
            sent=True,
            queue_item_id=queue_item_id,
            transport="grpc",
            error_message=None,
            retryable=False,
        )

    def _validate_payload(self, command: DeviceCommand) -> dict:
        if not is_chirpstack_downlink_topic(command.topic):
            raise ValueError(f"Unsupported ChirpStack downlink topic: {command.topic}")

        if not isinstance(command.payload, dict):
            raise ValueError("Command payload must be a JSON object")

        for field_name in ("devEui", "fPort", "data"):
            if field_name not in command.payload:
                raise ValueError(f"Missing field {field_name}")

        return command.payload

    def _decode_data(self, data_base64: str) -> bytes:
        try:
            return base64.b64decode(data_base64.encode("ascii"), validate=True)
        except Exception as exc:
            raise ValueError("data must be valid base64") from exc

def build_downlink_transport() -> DownlinkTransport:
    return ChirpStackGrpcDownlinkTransport()
