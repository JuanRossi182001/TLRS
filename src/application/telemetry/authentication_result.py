from dataclasses import dataclass

from src.models.device import Device


@dataclass(slots=True)
class AuthenticationResult:
    """
    Result of authenticating an incoming telemetry message.
    """
    
    is_authenticated: bool
    device: Device | None = None
    failure_reason: str | None = None