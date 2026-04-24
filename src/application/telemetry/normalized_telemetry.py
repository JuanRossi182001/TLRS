from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class NormalizedTelemetry:
    """
    Represents parsed and normalized telemetry data.
    """

    device_timestamp: datetime | None
    latitude: float
    longitude: float
    altitude: float | None = None
    accuracy: float | None = None
    extra: dict[str, Any] | None = None