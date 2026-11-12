"""Small, scoped SQL projections for historical analytics; no ORM materialization."""

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from time import perf_counter

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.analytics.historical_assignment import AssignmentRef
from src.application.analytics.performance_profile import ProcessingProfile
from src.application.analytics.spatial_assessment import SpatialObservationRef
from src.models.asset import Asset
from src.models.asset_group import AssetGroup, AssetGroupMember
from src.models.device import Device
from src.models.device_asset_assignment import DeviceAssetAssignment
from src.models.location import Location


class HistoricalRepositoryLimitExceeded(ValueError):
    pass


class HistoricalSpatialAnalyticsRepository:
    def __init__(self, db: AsyncSession, *, profile: ProcessingProfile | None = None):
        self.db = db
        self.profile = profile

    async def _execute(self, statement, *, page: bool = False, neighbor: bool = False):
        profile = self.profile
        started = perf_counter() if profile is not None else 0.0
        try:
            return await self.db.execute(statement)
        finally:
            if profile is not None:
                profile.sql_query_count += 1
                profile.sql_execute_seconds += perf_counter() - started
                profile.location_page_count += int(page)
                profile.neighbor_query_count += int(neighbor)

    def _materialize(self, result, factory=None):
        profile = self.profile
        started = perf_counter() if profile is not None else 0.0
        rows = result.all()
        values = rows if factory is None else [factory(*row) for row in rows]
        if profile is not None:
            profile.rows_fetched += len(rows)
            profile.row_materialization_seconds += perf_counter() - started
        return values

    async def accessible_asset_ids(self, *, client_id: int, asset_ids: Sequence[int]) -> set[int]:
        if not asset_ids:
            return set()
        result = await self._execute(select(Asset.id_asset).where(
            Asset.id_asset.in_(asset_ids), Asset.client_id == client_id, Asset.deleted == "N",
        ))
        return {row[0] for row in self._materialize(result)}

    async def group_asset_ids(self, *, client_id: int, group_id: int,
                              limit: int = 101) -> tuple[int, ...] | None:
        group = await self._execute(select(AssetGroup.id_asset_group).where(
            AssetGroup.id_asset_group == group_id, AssetGroup.client_id == client_id,
            AssetGroup.deleted == "N", AssetGroup.active.is_(True),
        ))
        if not self._materialize(group):
            return None
        result = await self._execute(
            select(AssetGroupMember.asset_id)
            .join(Asset, Asset.id_asset == AssetGroupMember.asset_id)
            .where(AssetGroupMember.asset_group_id == group_id, AssetGroupMember.deleted == "N",
                   Asset.client_id == client_id, Asset.deleted == "N")
            .order_by(AssetGroupMember.asset_id).limit(limit)
        )
        return tuple(row[0] for row in self._materialize(result))

    async def assignments(self, *, client_id: int, asset_ids: Sequence[int],
                          window_start: datetime, window_end: datetime,
                          limit: int = 501) -> tuple[AssignmentRef, ...]:
        if not asset_ids:
            return ()
        stmt = (
            select(DeviceAssetAssignment.id_device_asset_assignment, DeviceAssetAssignment.asset_id,
                   DeviceAssetAssignment.device_id, DeviceAssetAssignment.assigned_at,
                   DeviceAssetAssignment.unassigned_at)
            .join(Asset, Asset.id_asset == DeviceAssetAssignment.asset_id)
            .join(Device, Device.id_device == DeviceAssetAssignment.device_id)
            .where(DeviceAssetAssignment.asset_id.in_(asset_ids),
                   DeviceAssetAssignment.assigned_at < window_end,
                   or_(DeviceAssetAssignment.unassigned_at.is_(None),
                       DeviceAssetAssignment.unassigned_at > window_start),
                   Asset.client_id == client_id, Asset.deleted == "N",
                   Device.client_id == client_id)
            .order_by(DeviceAssetAssignment.assigned_at,
                      DeviceAssetAssignment.id_device_asset_assignment).limit(limit)
        )
        result = await self._execute(stmt)
        selected = tuple(self._materialize(result, AssignmentRef))
        if len(selected) == limit:
            return selected
        if not selected:
            return ()
        # Detect conflicting historical owners of any selected device, including
        # rows belonging to an animal outside the requested set.
        device_ids = {item.device_id for item in selected}
        conflicts = await self._execute(
            select(DeviceAssetAssignment.id_device_asset_assignment,
                   DeviceAssetAssignment.asset_id, DeviceAssetAssignment.device_id,
                   DeviceAssetAssignment.assigned_at, DeviceAssetAssignment.unassigned_at)
            .where(DeviceAssetAssignment.device_id.in_(device_ids),
                   DeviceAssetAssignment.assigned_at < window_end,
                   or_(DeviceAssetAssignment.unassigned_at.is_(None),
                       DeviceAssetAssignment.unassigned_at > window_start))
            .order_by(DeviceAssetAssignment.assigned_at,
                      DeviceAssetAssignment.id_device_asset_assignment)
            .limit(limit)
        )
        rows = self._materialize(conflicts, AssignmentRef)
        if len(rows) >= limit:
            raise HistoricalRepositoryLimitExceeded("Assignment limit exceeded.")
        return tuple(rows)

    async def estimate_location_count(self, *, client_id: int, asset_ids: Sequence[int],
                                      window_start: datetime, window_end: datetime,
                                      limit: int) -> int:
        """Bounded preflight estimate; stop after one row beyond the caller's cap."""
        if not asset_ids:
            return 0
        observed_at = func.coalesce(Location.device_timestamp, Location.received_at)
        bounded_ids = (
            select(Location.id_location)
            .join(DeviceAssetAssignment, DeviceAssetAssignment.device_id == Location.device_id)
            .join(Asset, Asset.id_asset == DeviceAssetAssignment.asset_id)
            .join(Device, Device.id_device == DeviceAssetAssignment.device_id)
            .where(
                Asset.id_asset.in_(asset_ids),
                Asset.client_id == client_id,
                Asset.deleted == "N",
                Device.client_id == client_id,
                Location.deleted == "N",
                observed_at >= window_start,
                observed_at < window_end,
                observed_at >= DeviceAssetAssignment.assigned_at,
                or_(DeviceAssetAssignment.unassigned_at.is_(None),
                    observed_at < DeviceAssetAssignment.unassigned_at),
            )
            .limit(limit)
            .subquery()
        )
        result = await self._execute(select(func.count()).select_from(bounded_ids))
        return int(result.scalar_one())

    def _locations_stmt(self, assignment: AssignmentRef, start: datetime | None,
                        end: datetime | None):
        observed_at = func.coalesce(Location.device_timestamp, Location.received_at)
        stmt = select(Location.id_location, observed_at.label("observed_at"),
                      Location.latitude, Location.longitude, Location.accuracy).where(
            Location.device_id == assignment.device_id, Location.deleted == "N",
            observed_at >= assignment.assigned_at,
        )
        if assignment.unassigned_at is not None:
            stmt = stmt.where(observed_at < assignment.unassigned_at)
        if start is not None:
            stmt = stmt.where(observed_at >= start)
        if end is not None:
            stmt = stmt.where(observed_at < end)
        return stmt, observed_at

    async def neighboring_locations(self, assignment: AssignmentRef, *,
                                    boundary: datetime, before: bool, count: int = 5) -> tuple[SpatialObservationRef, ...]:
        stmt, observed_at = self._locations_stmt(
            assignment, None if before else boundary, boundary if before else None
        )
        if before:
            stmt = stmt.order_by(observed_at.desc(), Location.id_location.desc())
        else:
            stmt = stmt.order_by(observed_at, Location.id_location)
        result = await self._execute(stmt.limit(count), neighbor=True)
        rows = self._materialize(result, SpatialObservationRef)
        if before:
            rows.reverse()
        return tuple(rows)

    async def iter_locations(self, assignment: AssignmentRef, *, start: datetime,
                             end: datetime, page_size: int = 500) -> AsyncIterator[SpatialObservationRef]:
        """Keyset pages; no OFFSET scans and no growing result collection."""
        cursor: tuple[datetime, int] | None = None
        while True:
            stmt, observed_at = self._locations_stmt(assignment, start, end)
            if cursor is not None:
                stmt = stmt.where(or_(observed_at > cursor[0],
                                      and_(observed_at == cursor[0], Location.id_location > cursor[1])))
            stmt = stmt.order_by(observed_at, Location.id_location).limit(page_size)
            result = await self._execute(stmt, page=True)
            rows = self._materialize(result, SpatialObservationRef)
            for row in rows:
                yield row
            if len(rows) < page_size:
                break
            cursor = rows[-1].observed_at, rows[-1].observation_id
