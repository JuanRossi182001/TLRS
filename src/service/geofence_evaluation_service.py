from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, func, cast
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import Geometry, Geography

from src.models.geofence import (
    FenceEventType,
    GeoFence,
    GeoFenceAssetState,
    GeoFenceEvent,
    GeoFenceStatus,
)
from src.models.location import Location
from src.models.device import Device
from src.models.asset import Asset
from src.service.device_command_service import DeviceCommandService
from src.service.geofence_membership_service import GeofenceMembershipService


@dataclass(slots=True)
class GeofenceEvaluationResult:
    fence_id: int
    level: GeoFenceStatus
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
            new_status = self._resolve_status(
                inside=row.inside,
                distance_to_boundary_meters=row.distance_to_boundary_meters,
                accuracy=location.accuracy,
            )

            state, previous_status = await self._get_or_create_asset_state(
                fence_id=row.fence_id,
                asset_id=device.asset_id,
                device_id=device.id_device,
                location_id=location.id_location,
                current_status=new_status,
                distance_to_boundary_meters=row.distance_to_boundary_meters,
                accuracy=location.accuracy,
            )

            event_type = self._resolve_event_type_from_transition(
                previous_status=previous_status,
                new_status=new_status,
            )

            self._update_asset_state(
                state=state,
                device_id=device.id_device,
                location_id=location.id_location,
                current_status=new_status,
                distance_to_boundary_meters=row.distance_to_boundary_meters,
                accuracy=location.accuracy,
            )

            event_created = event_type is not None
            if event_created:
                event = self._create_event(
                    fence_id=row.fence_id,
                    device_id=device.id_device,
                    asset_id=device.asset_id,
                    location_id=location.id_location,
                    event_type=event_type,
                    distance_to_boundary_meters=row.distance_to_boundary_meters,
                    accuracy=location.accuracy,
                )
                await self.db.flush()
                command_service = DeviceCommandService(self.db)
                await command_service.create_commands_for_geofence_event(
                    event=event,
                    device=device,
                )

            results.append(
                GeofenceEvaluationResult(
                    fence_id=row.fence_id,
                    level=new_status,
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
        membership_service = GeofenceMembershipService(self.db)
        effective_geofence_ids = await membership_service.get_effective_geofence_ids_for_asset(
            asset_id
        )
        if not effective_geofence_ids:
            return []

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
                Location,
                Location.id_location == location_id,
            )
            .where(
                GeoFence.id_geofence.in_(effective_geofence_ids),
                GeoFence.active.is_(True),
                GeoFence.deleted == "N",
            )
        )

        result = await self.db.execute(stmt)
        return result.all()

    async def _get_or_create_asset_state(
        self,
        fence_id: int,
        asset_id: int,
        device_id: int,
        location_id: int,
        current_status: GeoFenceStatus,
        distance_to_boundary_meters: float | None,
        accuracy: float | None,
    ) -> tuple[GeoFenceAssetState, GeoFenceStatus | None]:
        now = datetime.utcnow()

        insert_stmt = (
            insert(GeoFenceAssetState)
            .values(
                fence_id=fence_id,
                asset_id=asset_id,
                device_id=device_id,
                current_status=current_status,
                last_location_id=location_id,
                last_distance_to_boundary_meters=distance_to_boundary_meters,
                last_accuracy=accuracy,
                first_detected_at=now,
                last_evaluated_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                constraint="uq_geofence_asset_state_fence_asset",
            )
            .returning(GeoFenceAssetState.id_state)
        )
        insert_result = await self.db.execute(insert_stmt)
        inserted_state_id = insert_result.scalar_one_or_none()

        stmt = (
            select(GeoFenceAssetState)
            .where(
                GeoFenceAssetState.fence_id == fence_id,
                GeoFenceAssetState.asset_id == asset_id,
            )
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        state = result.scalar_one()

        if inserted_state_id is not None:
            return state, None

        return state, state.current_status

    def _resolve_status(
        self,
        inside: bool,
        distance_to_boundary_meters: float | None,
        accuracy: float | None,
    ) -> GeoFenceStatus:
        if accuracy is not None and accuracy >= self.gps_uncertain_accuracy_meters:
            return GeoFenceStatus.GPS_UNCERTAIN

        if not inside:
            return GeoFenceStatus.OUTSIDE

        if (
            distance_to_boundary_meters is not None
            and distance_to_boundary_meters <= self.near_limit_threshold_meters
        ):
            return GeoFenceStatus.NEAR_LIMIT

        return GeoFenceStatus.SAFE

    def _resolve_event_type_from_transition(
        self,
        previous_status: GeoFenceStatus | None,
        new_status: GeoFenceStatus,
    ) -> FenceEventType | None:
        if previous_status == new_status:
            return None

        return self.GEOFENCE_TRANSITION_EVENTS.get((previous_status, new_status))

    def _update_asset_state(
        self,
        state: GeoFenceAssetState,
        device_id: int,
        location_id: int,
        current_status: GeoFenceStatus,
        distance_to_boundary_meters: float | None,
        accuracy: float | None,
    ) -> None:
        now = datetime.utcnow()
        state.current_status = current_status
        state.device_id = device_id
        state.last_location_id = location_id
        state.last_distance_to_boundary_meters = distance_to_boundary_meters
        state.last_accuracy = accuracy
        state.last_evaluated_at = now
        state.updated_at = now
        self.db.add(state)

    def _create_event(
        self,
        fence_id: int,
        device_id: int,
        asset_id: int,
        location_id: int,
        event_type: FenceEventType,
        distance_to_boundary_meters: float | None,
        accuracy: float | None,
    ) -> GeoFenceEvent:
        event = GeoFenceEvent(
            fence_id=fence_id,
            device_id=device_id,
            asset_id=asset_id,
            location_id=location_id,
            event_type=event_type,
            distance_to_boundary_meters=distance_to_boundary_meters,
            accuracy=accuracy,
        )
        self.db.add(event)
        return event




    GEOFENCE_TRANSITION_EVENTS: dict[
    tuple[GeoFenceStatus | None, GeoFenceStatus],
    FenceEventType,
    ] = {
        (None, GeoFenceStatus.NEAR_LIMIT): FenceEventType.NEAR_LIMIT,
        (None, GeoFenceStatus.OUTSIDE): FenceEventType.EXITED,
        (None, GeoFenceStatus.GPS_UNCERTAIN): FenceEventType.GPS_UNCERTAIN,

        (GeoFenceStatus.SAFE, GeoFenceStatus.NEAR_LIMIT): FenceEventType.NEAR_LIMIT,
        (GeoFenceStatus.SAFE, GeoFenceStatus.OUTSIDE): FenceEventType.EXITED,
        (GeoFenceStatus.SAFE, GeoFenceStatus.GPS_UNCERTAIN): FenceEventType.GPS_UNCERTAIN,

        (GeoFenceStatus.NEAR_LIMIT, GeoFenceStatus.OUTSIDE): FenceEventType.EXITED,
        (GeoFenceStatus.NEAR_LIMIT, GeoFenceStatus.GPS_UNCERTAIN): FenceEventType.GPS_UNCERTAIN,

        (GeoFenceStatus.OUTSIDE, GeoFenceStatus.SAFE): FenceEventType.RETURNED,
        (GeoFenceStatus.OUTSIDE, GeoFenceStatus.NEAR_LIMIT): FenceEventType.RETURNED,
        (GeoFenceStatus.OUTSIDE, GeoFenceStatus.GPS_UNCERTAIN): FenceEventType.GPS_UNCERTAIN,

        (GeoFenceStatus.GPS_UNCERTAIN, GeoFenceStatus.NEAR_LIMIT): FenceEventType.NEAR_LIMIT,
        (GeoFenceStatus.GPS_UNCERTAIN, GeoFenceStatus.OUTSIDE): FenceEventType.EXITED,
    }


    async def get_asset_states(
        self,
        client_id: int,
        skip: int = 0,
        limit: int = 100,
    ):
        filters = self._asset_state_filters(client_id=client_id)

        total_stmt = select(func.count()).select_from(
            self._asset_states_select().where(*filters).order_by(None).subquery()
        )
        total_result = await self.db.execute(total_stmt)
        total = total_result.scalar_one()

        items_stmt = self._asset_states_select().where(*filters).offset(skip).limit(limit)
        items_result = await self.db.execute(items_stmt)
        return total, list(items_result.mappings().all())

    async def get_asset_states_by_asset_id(
        self,
        client_id: int,
        asset_id: int,
    ):
        asset = await self._get_asset_for_client(
            client_id=client_id,
            asset_id=asset_id,
        )
        if asset is None:
            return None

        stmt = self._asset_states_select().where(
            *self._asset_state_filters(client_id=client_id, asset_id=asset_id)
        )
        result = await self.db.execute(stmt)
        return list(result.mappings().all())

    async def _get_asset_for_client(
        self,
        client_id: int,
        asset_id: int,
    ) -> Asset | None:
        stmt = select(Asset).where(
            Asset.id_asset == asset_id,
            Asset.client_id == client_id,
            Asset.deleted == "N",
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    def _asset_states_select(self):
        memberships = GeofenceMembershipService(self.db).effective_memberships_subquery()
        stmt = (
            select(
                Asset.id_asset,
                Asset.asset_type.label("asset_name"),
                Asset.asset_type,
                Asset.serial.label("asset_serial"),
                Device.id_device,
                Device.serial.label("device_serial"),
                Device.name.label("device_name"),
                GeoFenceAssetState.fence_id,
                GeoFence.name.label("geofence_name"),
                GeoFenceAssetState.current_status,
                Location.id_location.label("last_location_id"),
                Location.latitude,
                Location.longitude,
                GeoFenceAssetState.last_distance_to_boundary_meters,
                GeoFenceAssetState.last_accuracy,
                GeoFenceAssetState.last_evaluated_at,
            )
            .select_from(GeoFenceAssetState)
            .join(
                memberships,
                (memberships.c.fence_id == GeoFenceAssetState.fence_id)
                & (memberships.c.asset_id == GeoFenceAssetState.asset_id),
            )
            .join(
                Asset,
                Asset.id_asset == GeoFenceAssetState.asset_id,
            )
            .join(
                Device,
                Device.id_device == GeoFenceAssetState.device_id,
            )
            .join(
                GeoFence,
                GeoFence.id_geofence == GeoFenceAssetState.fence_id,
            )
            .join(
                Location,
                Location.id_location == GeoFenceAssetState.last_location_id,
            )
            .order_by(GeoFenceAssetState.last_evaluated_at.desc())
        )
        return stmt

    def _asset_state_filters(self, client_id: int, asset_id: int | None = None):
        filters = [
            GeoFence.client_id == client_id,
            GeoFence.deleted == "N",
            GeoFence.active.is_(True),
            Asset.deleted == "N",
        ]
        if asset_id is not None:
            filters.append(Asset.id_asset == asset_id)

        return filters
