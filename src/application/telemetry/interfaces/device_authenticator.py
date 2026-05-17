from abc import ABC, abstractmethod

from src.application.telemetry.incoming_telemetry_envelope import IncomingTelemetryEnvelope
from src.application.telemetry.authentication_result import AuthenticationResult


class DeviceAuthenticator(ABC):
    """
    Contract for device authentication strategies.
    Responsible for validating whether an incoming telemetry message
    comes from a legitimate registered device.
    """

    @abstractmethod
    async def authenticate(
        self,
        envelope: IncomingTelemetryEnvelope,
    ) -> AuthenticationResult:
        """
        Authenticates a device based on the information present
        in the incoming telemetry envelope.
        """
        raise NotImplementedError
