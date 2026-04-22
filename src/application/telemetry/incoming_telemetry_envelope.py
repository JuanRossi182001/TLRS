from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.models.device import DeviceCommunicationProtocol


@dataclass(slots=True)
class IncomingTelemetryEnvelope:
    """
    Common representation of any telemetry message entering the system,
    independently of whether it came from HTTP or MQTT.
    """

    transport_protocol: DeviceCommunicationProtocol
    raw_payload: str
    received_at: datetime
    source_ip: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    topic: str | None = None
    auth_metadata: dict[str, Any] = field(default_factory=dict)