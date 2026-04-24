from dataclasses import dataclass

from src.models.device import Device
from src.models.location import Location


@dataclass(slots=True)
class TelemetryIngestionResult:
    """
    Result of processing an incoming telemetry message.
    """

    success: bool
    device: Device | None = None
    location: Location | None = None
    failure_reason: str | None = None