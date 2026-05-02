import json
from datetime import datetime

from src.application.telemetry.interfaces.telemetry_parser import TelemetryParser
from src.application.telemetry.incoming_telemetry_envelope import IncomingTelemetryEnvelope
from src.application.telemetry.normalized_telemetry import NormalizedTelemetry


class JsonTelemetryParser(TelemetryParser):
    """
    Here we use the TelemetryParser interface to define a new telemetry parser.
    Parses JSON telemetry payloads.
    """

    def parse(
        self,
        envelope: IncomingTelemetryEnvelope,
    ) -> NormalizedTelemetry:

        try:
            data = json.loads(envelope.raw_payload)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON payload")

        lat = data.get("lat")
        lng = data.get("lng")

        if lat is None or lng is None:
            raise ValueError("Missing latitude or longitude")

        timestamp = data.get("timestamp")

        device_timestamp = None
        if timestamp:
            try:
                device_timestamp = datetime.fromtimestamp(int(timestamp))
            except Exception:
                raise ValueError("Invalid timestamp")

        return NormalizedTelemetry(
            device_timestamp=device_timestamp,
            latitude=float(lat),
            longitude=float(lng),
            altitude=self._safe_float(data.get("altitude")),
            accuracy=self._safe_float(data.get("accuracy")),
            extra=self._extract_extra(data),
        )

    def _safe_float(self, value):
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _extract_extra(self, data: dict) -> dict:
        known_keys = {"lat", "lng", "timestamp", "altitude", "accuracy", "signature"}
        return {k: v for k, v in data.items() if k not in known_keys}