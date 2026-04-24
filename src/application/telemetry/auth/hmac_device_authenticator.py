import hmac
import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.application.telemetry.authentication_result import AuthenticationResult
from src.application.telemetry.incoming_telemetry_envelope import IncomingTelemetryEnvelope
from src.application.telemetry.interfaces.device_authenticator import DeviceAuthenticator
from src.models.device import Device, DeviceCredential, CredentialStatus



class HmacDeviceAuthenticator(DeviceAuthenticator):
    """
    Here we use the DeviceUthenticator interface to define a new device authentication
    Authenticates devices using HMAC signature.
    """

    def __init__(self, db: Session, max_time_skew_seconds: int = 180):
        self.db = db
        self.max_time_skew_seconds = max_time_skew_seconds

    def authenticate(
        self,
        envelope: IncomingTelemetryEnvelope,
    ) -> AuthenticationResult:

        serial = envelope.auth_metadata.get("x-device-serial")
        signature = envelope.auth_metadata.get("x-signature")
        timestamp = envelope.auth_metadata.get("x-timestamp")

        if not serial:
            return self._fail("Missing device serial")

        if not signature:
            return self._fail("Missing signature")

        if not timestamp:
            return self._fail("Missing timestamp")

        device = (
            self.db.query(Device)
            .filter(Device.serial == serial,
                    Device.active == True)
            .first()
        )

        if not device:
            return self._fail("Device not found or inactive")

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
            return self._fail("No active credential found")

        # --- Validar timestamp ---
        if not self._is_timestamp_valid(timestamp):
            return self._fail("Invalid or expired timestamp")

        # --- Validar firma ---
        if not self._is_signature_valid(
            envelope.raw_payload,
            timestamp,
            credential.secret,
            signature,
        ):
            return self._fail("Invalid signature")

        return AuthenticationResult(
            is_authenticated=True,
            device=device,
        )

    def _is_signature_valid(
        self,
        payload: str,
        timestamp: str,
        secret: str,
        received_signature: str,
    ) -> bool:

        message = f"{payload}{timestamp}".encode()

        expected_signature = hmac.new(
            key=secret.encode(),
            msg=message,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_signature, received_signature)

    def _is_timestamp_valid(self, timestamp: str) -> bool:
        try:
            request_time = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        except Exception:
            return False

        now = datetime.now(timezone.utc)
        delta = abs((now - request_time).total_seconds())

        return delta <= self.max_time_skew_seconds

    def _fail(self, reason: str) -> AuthenticationResult:
        return AuthenticationResult(
            is_authenticated=False,
            failure_reason=reason,
        )