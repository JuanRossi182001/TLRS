from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select, func, cast
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import Geometry, Geography

from src.models.geofence import GeoFence, GeoFenceAssignment, GeoFenceEvent, FenceEventType
from src.models.location import Location
from src.models.device import Device


class GeofenceEvaluationLevel(str, Enum):
    INSIDE = "INSIDE"
    NEAR_LIMIT = "NEAR_LIMIT"
    OUTSIDE = "OUTSIDE"
    GPS_UNCERTAIN = "GPS_UNCERTAIN"


@dataclass(slots=True)
class GeofenceEvaluationResult:
    fence_id: int
    level: GeofenceEvaluationLevel
    distance_to_boundary_meters: float | None
    accuracy: float | None
    event_created: bool


class GeoFenceEvaluationService:
    def __init__(
        self,
        db: AsyncSession,
        near_limit_threshold_meters: float = 50.0,
        gps_uncertain_accuracy_meters: float = 30.0,
    ):
        self.db = db
        self.near_limit_threshold_meters = near_limit_threshold_meters
        self.gps_uncertain_accuracy_meters = gps_uncertain_accuracy_meters

    async def evaluate_location(
        self,
        device_id: int,
        location_id: int,
    ) -> list[GeofenceEvaluationResult]:
        device = await self._get_device(device_id)
        if device is None or device.asset_id is None:
            return []

        location = await self._get_location(location_id)
        if location is None:
            return []

        rows = await self._get_assigned_geofence_spatial_results(
            asset_id=device.asset_id,
            location_id=location_id,
        )

        results: list[GeofenceEvaluationResult] = []

        for row in rows:
            level = self._resolve_level(
                inside=row.inside,
                distance_to_boundary_meters=row.distance_to_boundary_meters,
                accuracy=location.accuracy,
            )

            event_type = self._map_level_to_event_type(level)

            event_created = False
            if event_type is not None:
                event = GeoFenceEvent(
                    fence_id=row.fence_id,
                    device_id=device.id_device,
                    asset_id=device.asset_id,
                    location_id=location.id_location,
                    event_type=event_type,
                    distance_to_boundary_meters=row.distance_to_boundary_meters,
                    accuracy=location.accuracy,
                )
                self.db.add(event)
                event_created = True

            results.append(
                GeofenceEvaluationResult(
                    fence_id=row.fence_id,
                    level=level,
                    distance_to_boundary_meters=row.distance_to_boundary_meters,
                    accuracy=location.accuracy,
                    event_created=event_created,
                )
            )

        return results

    async def _get_device(self, device_id: int) -> Device | None:
        stmt = select(Device).where(Device.id_device == device_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_location(self, location_id: int) -> Location | None:
        stmt = select(Location).where(Location.id_location == location_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_assigned_geofence_spatial_results(
        self,
        asset_id: int,
        location_id: int,
    ):
        location_point_geometry = cast(Location.point, Geometry(geometry_type="POINT", srid=4326))

        boundary_geography = cast(
            func.ST_Boundary(GeoFence.shape),
            Geography(geometry_type="LINESTRING", srid=4326),
        )

        stmt = (
            select(
                GeoFence.id_geofence.label("fence_id"),
                func.ST_Covers(
                    GeoFence.shape,
                    location_point_geometry,
                ).label("inside"),
                func.ST_Distance(
                    cast(location_point_geometry, Geography(geometry_type="POINT", srid=4326)),
                    boundary_geography,
                ).label("distance_to_boundary_meters"),
            )
            .join(
                GeoFenceAssignment,
                GeoFenceAssignment.fence_id == GeoFence.id_geofence,
            )
            .join(
                Location,
                Location.id_location == location_id,
            )
            .where(
                GeoFenceAssignment.asset_id == asset_id,
                GeoFenceAssignment.active.is_(True),
                GeoFenceAssignment.deleted == "N",
                GeoFence.active.is_(True),
                GeoFence.deleted == "N",
            )
        )

        result = await self.db.execute(stmt)
        return result.all()

    def _resolve_level(
        self,
        inside: bool,
        distance_to_boundary_meters: float | None,
        accuracy: float | None,
    ) -> GeofenceEvaluationLevel:
        if accuracy is not None and accuracy >= self.gps_uncertain_accuracy_meters:
            return GeofenceEvaluationLevel.GPS_UNCERTAIN

        if not inside:
            return GeofenceEvaluationLevel.OUTSIDE

        if (
            distance_to_boundary_meters is not None
            and distance_to_boundary_meters <= self.near_limit_threshold_meters
        ):
            return GeofenceEvaluationLevel.NEAR_LIMIT

        return GeofenceEvaluationLevel.INSIDE

    def _map_level_to_event_type(
        self,
        level: GeofenceEvaluationLevel,
    ) -> FenceEventType | None:
        if level == GeofenceEvaluationLevel.GPS_UNCERTAIN:
            return FenceEventType.GPS_UNCERTAIN

        if level == GeofenceEvaluationLevel.OUTSIDE:
            return FenceEventType.EXITED

        if level == GeofenceEvaluationLevel.NEAR_LIMIT:
            return FenceEventType.NEAR_LIMIT

        return None