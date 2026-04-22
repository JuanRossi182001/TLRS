from datetime import datetime

from src.application.telemetry.incoming_telemetry_envelope import IncomingTelemetryEnvelope
from src.application.telemetry.interfaces.telemetry_ingress import TelemetryIngress
from src.models.device import DeviceCommunicationProtocol


class HttpTelemetryIngress(TelemetryIngress):
    """
    HTTP implementation of telemetry ingress interface.

    Receives raw HTTP request data and converts it into
    an IncomingTelemetryEnvelope.
    """

    def build_envelope(
        self,
        raw_payload: str,
        headers: dict[str, str] | None = None,
        source_ip: str | None = None,
    ) -> IncomingTelemetryEnvelope:
        normalized_headers = headers or {}

        auth_metadata = self._extract_auth_metadata(normalized_headers)

        return IncomingTelemetryEnvelope(
            transport_protocol=DeviceCommunicationProtocol.HTTP,
            raw_payload=raw_payload,
            received_at=datetime.utcnow(),
            source_ip=source_ip,
            headers=normalized_headers,
            topic=None,
            auth_metadata=auth_metadata,
        )

    def _extract_auth_metadata(self, headers: dict[str, str]) -> dict[str, str]:
        """
        Extracts authentication-related metadata from HTTP headers.
        This does not validate authentication, it only prepares data
        for later authentication processing.
        """
        auth_metadata: dict[str, str] = {}

        authorization = headers.get("authorization")
        x_device_serial = headers.get("x-device-serial")
        x_signature = headers.get("x-signature")
        x_timestamp = headers.get("x-timestamp")

        if authorization:
            auth_metadata["authorization"] = authorization

        if x_device_serial:
            auth_metadata["x_device_serial"] = x_device_serial

        if x_signature:
            auth_metadata["x_signature"] = x_signature

        if x_timestamp:
            auth_metadata["x_timestamp"] = x_timestamp

        return auth_metadata