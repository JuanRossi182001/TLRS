from src.application.telemetry.authentication_result import AuthenticationResult
from src.application.telemetry.incoming_telemetry_envelope import IncomingTelemetryEnvelope
from src.application.telemetry.interfaces.device_authenticator import DeviceAuthenticator
from src.models.device import Device, DeviceCredential, CredentialStatus
from sqlalchemy.orm import Session


class ApiKeyDeviceAuthenticator(DeviceAuthenticator):
    """
    Here we use the DeviceUthenticator interface to define a new device authentication strategy.
    Authenticates devices using a device serial + API key strategy.
    """

    def __init__(self, db: Session):
        self.db = db

    def authenticate(
        self,
        envelope: IncomingTelemetryEnvelope,
    ) -> AuthenticationResult:
        device_serial = envelope.auth_metadata.get("x-device-serial")
        api_key = envelope.auth_metadata.get("x-api-key")

        if not device_serial:
            return AuthenticationResult(
                is_authenticated=False,
                failure_reason="Missing device serial.",
            )

        if not api_key:
            return AuthenticationResult(
                is_authenticated=False,
                failure_reason="Missing API key.",
            )

        device = (
            self.db.query(Device)
            .filter(Device.serial == device_serial)
            .first()
        )

        if not device:
            return AuthenticationResult(
                is_authenticated=False,
                failure_reason="Device not found.",
            )

        if not device.active:
            return AuthenticationResult(
                is_authenticated=False,
                failure_reason="Device is inactive.",
            )

        credential = (
            self.db.query(DeviceCredential)
            .filter(
                DeviceCredential.device_id == device.id_device,
                DeviceCredential.status == CredentialStatus.ACTIVE,
            )
            .order_by(DeviceCredential.created_at.desc())
            .first()
        )

        if not credential:
            return AuthenticationResult(
                is_authenticated=False,
                failure_reason="Active credential not found.",
            )

        if credential.secret != api_key:
            return AuthenticationResult(
                is_authenticated=False,
                failure_reason="Invalid API key.",
            )

        return AuthenticationResult(
            is_authenticated=True,
            device=device,
            failure_reason=None,
        )