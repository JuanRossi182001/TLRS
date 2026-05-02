import json
from datetime import datetime

from src.application.telemetry.incoming_telemetry_envelope import IncomingTelemetryEnvelope
from src.application.telemetry.interfaces.telemetry_ingress import TelemetryIngress
from src.models.device import DeviceCommunicationProtocol


class MqttTelemetryIngress(TelemetryIngress):
    """
    MQTT implementation of telemetry ingress.

    Converts an MQTT message into an IncomingTelemetryEnvelope.
    """

    def build_envelope(
        self,
        raw_payload: str,
        topic: str,
        qos: int | None = None,
        retain: bool | None = None,
        mqtt_client_id: str | None = None,
        mqtt_username: str | None = None,
    ) -> IncomingTelemetryEnvelope:
        device_serial = self._extract_device_serial_from_topic(topic)

        auth_metadata: dict[str, str] = {
            "mqtt-topic": topic,
        }

        if device_serial:
            # Reuses the same key expected by HmacDeviceAuthenticator
            auth_metadata["x-device-serial"] = device_serial
            auth_metadata["mqtt-device-serial"] = device_serial

        auth_metadata.update(
            self._extract_auth_from_payload(raw_payload)
        )

        if mqtt_client_id:
            auth_metadata["mqtt-client-id"] = mqtt_client_id

        if mqtt_username:
            auth_metadata["mqtt-username"] = mqtt_username

        if qos is not None:
            auth_metadata["mqtt-qos"] = str(qos)

        if retain is not None:
            auth_metadata["mqtt-retain"] = str(retain)

        auth_metadata = self._normalize_auth_metadata_keys(auth_metadata)

        return IncomingTelemetryEnvelope(
            transport_protocol=DeviceCommunicationProtocol.MQTT,
            raw_payload=raw_payload,
            received_at=datetime.utcnow(),
            source_ip=None,
            headers={},
            topic=topic,
            auth_metadata=auth_metadata,
        )

    def _extract_device_serial_from_topic(self, topic: str) -> str | None:
        """
        Expected topic format:
        gps/devices/{device_serial}/location

        Example:
        gps/devices/AAA-001/location
        """
        parts = topic.split("/")

        if len(parts) != 4:
            return None

        namespace, devices_segment, device_serial, message_type = parts

        if namespace != "gps":
            return None

        if devices_segment != "devices":
            return None

        if message_type != "location":
            return None

        return device_serial

    def _normalize_auth_metadata_keys(
        self,
        auth_metadata: dict[str, str],
    ) -> dict[str, str]:
        return {
            key.replace("_", "-"): value
            for key, value in auth_metadata.items()
        }

    def _extract_auth_from_payload(self, raw_payload: str) -> dict[str, str]:
        """
        Extracts HMAC-related metadata from MQTT payload.

        In MQTT we do not have HTTP headers, so signature and timestamp
        may come inside the JSON payload.
        """
        try:
            data = json.loads(raw_payload)
        except json.JSONDecodeError:
            return {}

        if not isinstance(data, dict):
            return {}

        auth_metadata: dict[str, str] = {}

        timestamp = data.get("timestamp")
        signature = data.get("signature")

        if timestamp is not None:
            auth_metadata["x-timestamp"] = str(timestamp)

        if signature:
            auth_metadata["x-signature"] = str(signature)

        return auth_metadata
