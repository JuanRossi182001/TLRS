from datetime import datetime

from geoalchemy2.elements import WKTElement
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.telemetry.normalized_telemetry import NormalizedTelemetry
from src.models.device import Device, DeviceState
from src.models.location import Location
from src.service.geofence_evaluation_service import (
    GeofenceEvaluationResult,
    GeoFenceEvaluationService,
)


class LocationIngestionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def persist_location(
        self,
        device: Device,
        normalized_telemetry: NormalizedTelemetry,
        received_at: datetime,
    ) -> Location:
        location, _ = await self.persist_location_with_statuses(
            device=device,
            normalized_telemetry=normalized_telemetry,
            received_at=received_at,
        )
        return location

    async def persist_location_with_statuses(
        self,
        device: Device,
        normalized_telemetry: NormalizedTelemetry,
        received_at: datetime,
    ) -> tuple[Location, list[GeofenceEvaluationResult]]:
        location = Location(
            device_id=device.id_device,
            latitude=normalized_telemetry.latitude,
            longitude=normalized_telemetry.longitude,
            point=WKTElement(
                f"POINT({normalized_telemetry.longitude} {normalized_telemetry.latitude})",
                srid=4326,
            ),
            altitude=normalized_telemetry.altitude,
            accuracy=normalized_telemetry.accuracy,
            device_timestamp=normalized_telemetry.device_timestamp,
            received_at=received_at,
            geometry=None,
        )
        self.db.add(location)
        await self.db.flush()

        device.state = DeviceState.ON
        device.last_seen_at = received_at
        self.db.add(device)

        evaluation_service = GeoFenceEvaluationService(self.db)
        geofence_states = await evaluation_service.evaluate_location(
            device.id_device,
            location.id_location,
        )

        return location, geofence_states
