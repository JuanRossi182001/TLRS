from abc import ABC, abstractmethod

from src.application.telemetry.incoming_telemetry_envelope import IncomingTelemetryEnvelope


class TelemetryIngress(ABC):
    """
    Contract for any telemetry input adapter.

    Its responsibility is to receive external telemetry input
    and transform it into an IncomingTelemetryEnvelope.
    """

    @abstractmethod
    def build_envelope(self, *args, **kwargs) -> IncomingTelemetryEnvelope:
        """
        Builds a normalized input envelope from an external transport-specific input.
        """
        raise NotImplementedError