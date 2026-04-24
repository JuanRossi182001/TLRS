from abc import ABC, abstractmethod

from src.application.telemetry.incoming_telemetry_envelope import IncomingTelemetryEnvelope
from src.application.telemetry.normalized_telemetry import NormalizedTelemetry


class TelemetryParser(ABC):
    """
    Contract for parsing raw telemetry into normalized data.
    """

    @abstractmethod
    def parse(
        self,
        envelope: IncomingTelemetryEnvelope,
    ) -> NormalizedTelemetry:
        raise NotImplementedError