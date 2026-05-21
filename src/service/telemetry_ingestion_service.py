from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.elements import WKTElement

from src.application.telemetry.incoming_telemetry_envelope import IncomingTelemetryEnvelope
from src.application.telemetry.interfaces.device_authenticator import DeviceAuthenticator
from src.application.telemetry.interfaces.telemetry_parser import TelemetryParser
from src.application.telemetry.telemetry_ingestion_result import TelemetryIngestionResult
from src.models.device import DeviceState
from src.models.location import Location
from src.models.telemetryMessage import TelemetryMessage


class TelemetryIngestionService:
    """
    Orchestrates the full telemetry ingestion flow:
    authenticate -> persist raw message -> parse -> persist location.
    """

    def __init__(
        self,
        db: AsyncSession,
        authenticator: DeviceAuthenticator,
        parser: TelemetryParser,
    ):
        self.db = db
        self.authenticator = authenticator
        self.parser = parser

    async def ingest(
        self,
        envelope: IncomingTelemetryEnvelope,
    ) -> TelemetryIngestionResult:
        auth_result = await self.authenticator.authenticate(envelope)

        if not auth_result.is_authenticated or not auth_result.device:
            return TelemetryIngestionResult(
                success=False,
                failure_reason=auth_result.failure_reason,
            )

        device = auth_result.device

        telemetry_message = await self._store_raw_telemetry(device.id_device, envelope)
        await self.db.commit() # i commit here for the first time to save the raw message for precaution if the parsing fails.
                         # i took this decision because i dont want to loose the raw message if the parsing fails.
        try:
            normalized_telemetry = self.parser.parse(envelope)
        except ValueError as exc:
            telemetry_message.error_message = str(exc)
            self.db.add(telemetry_message)
            await self.db.commit()
            return TelemetryIngestionResult(
                success=False,
                device=device,
                failure_reason=str(exc),
            )

        location = await self._store_location(device.id_device, normalized_telemetry, envelope)
        telemetry_message.processed = True
        
        self.db.add(telemetry_message)
        self._update_device_state_last_seen(device, envelope)
        await self.db.commit()

        return TelemetryIngestionResult(
            success=True,
            device=device,
            location=location,
        )

    async def _store_raw_telemetry(
        self,
        device_id: int,
        envelope: IncomingTelemetryEnvelope,
    ) -> TelemetryMessage:
        telemetry_message = TelemetryMessage(
            device_id=device_id,
            received_at=envelope.received_at,
            raw_payload=envelope.raw_payload,
            protocol=envelope.transport_protocol,
            source_ip=envelope.source_ip,
            processed=False,
            error_message=None,
        )
        self.db.add(telemetry_message)
        await self.db.flush()
        return telemetry_message

    async def _store_location(
    self,
    device_id: int,
    normalized_telemetry,
    envelope: IncomingTelemetryEnvelope,
    ) -> Location:
        location = Location(
            device_id=device_id,
            latitude=normalized_telemetry.latitude,
            longitude=normalized_telemetry.longitude,
            point=WKTElement(
                f"POINT({normalized_telemetry.longitude} {normalized_telemetry.latitude})",
                srid=4326,
            ),
            altitude=normalized_telemetry.altitude,
            accuracy=normalized_telemetry.accuracy,
            device_timestamp=normalized_telemetry.device_timestamp,
            received_at=envelope.received_at,
            geometry=None,
        )
        self.db.add(location)
        await self.db.flush()
        return location

    def _update_device_state_last_seen(self, device, envelope: IncomingTelemetryEnvelope) -> None:
        device.state = DeviceState.ON
        device.last_seen_at = envelope.received_at
