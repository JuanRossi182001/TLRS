"""Client-scoped, bounded historical animal-seconds; no HTTP dependencies."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from time import monotonic, perf_counter
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.analytics.historical_assignment import (
    AssignmentRef, resolve_assignment_windows, temporal_coverage_ratio,
)
from src.application.analytics.historical_engine import RollingTemporalAnalyzer
from src.application.analytics.observation_attribution import (
    TemporalObservationRef, attribute_observed_time_to_observations,
)
from src.application.analytics.observation_bucketing import bucket_observation_contributions
from src.application.analytics.performance_profile import ProcessingProfile
from src.application.analytics.observed_time import calculate_observed_time
from src.application.analytics.spatial_aggregation import (
    SpatialTemporalBucket, aggregate_spatial_time,
)
from src.application.analytics.spatial_assessment import (
    SpatialAssessmentConfig, SpatialObservationRef, assess_spatial_interval,
)
from src.application.analytics.spatial_grid import SpatialGridConfig
from src.application.analytics.spatial_qualification import _qualify_generated_interval
from src.application.analytics.temporal_continuity import ContinuityStatus
from src.application.analytics.temporal_sampling import calculate_bucket_resolution
from src.service.historical_spatial_analytics_repository import (
    HistoricalRepositoryLimitExceeded, HistoricalSpatialAnalyticsRepository,
)


class HistoricalAnalyticsError(ValueError):
    pass


class HistoricalAnalyticsNotFound(HistoricalAnalyticsError):
    pass


class HistoricalAnalyticsLimitExceeded(HistoricalAnalyticsError):
    pass


@dataclass(frozen=True, slots=True)
class HistoricalAnalyticsLimits:
    max_assets: int = 100
    max_assignments: int = 500
    max_locations: int = 500_000
    max_fragments: int = 1_000_000
    max_cells: int = 25_000
    max_results: int = 50_000
    page_size: int = 500
    max_query_seconds: float = 30.0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name == "max_query_seconds":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                    raise HistoricalAnalyticsError(f"{name} must be finite and positive.")
            elif isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise HistoricalAnalyticsError(f"{name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class HistoricalSpatialAnalyticsMetadata:
    window_start: datetime
    window_end: datetime
    requested_seconds: float
    eligible_assignment_seconds: float
    assessed_seconds: float
    unassessed_assignment_seconds: float
    observed_seconds: float
    gap_seconds: float
    indeterminate_seconds: float
    unknown_seconds: float
    spatially_eligible_seconds: float
    displacement_seconds: float
    spatially_uncertain_seconds: float
    other_excluded_seconds: float
    cell_boundary_uncertain_seconds: float
    outside_grid_seconds: float
    dwell_seconds: float
    temporal_coverage_ratio: float | None
    raw_location_count: int
    eligible_location_count: int
    processed_location_count: int
    device_count: int
    asset_count: int
    bucket_seconds: int
    spatial_cell_size_meters: float
    crs: str


@dataclass(frozen=True, slots=True)
class HistoricalSpatialAnalyticsResult:
    buckets: tuple[SpatialTemporalBucket, ...]
    metadata: HistoricalSpatialAnalyticsMetadata


class _Totals:
    def __init__(self) -> None:
        self.assessed = timedelta()
        self.observed = timedelta()
        self.gap = timedelta()
        self.indeterminate = timedelta()
        self.eligible = timedelta()
        self.displaced = timedelta()
        self.uncertain = timedelta()
        self.excluded = timedelta()
        self.boundary = timedelta()
        self.outside = timedelta()
        self.dwell = timedelta()
        self.raw_count = 0
        self.eligible_count = 0
        self.processed_count = 0
        self.fragments = 0
        # Store only the last observation per output cell: an observation's
        # RIGHT and LEFT halves are adjacent in chronological input order.
        self.cells: dict[tuple[int, datetime, str], tuple[SpatialTemporalBucket, timedelta, int, int | None]] = {}
        self.cell_ids: set[str] = set()


class HistoricalSpatialAnalyticsService:
    def __init__(self, db: AsyncSession, *,
                 repository: HistoricalSpatialAnalyticsRepository | None = None,
                 profile: ProcessingProfile | None = None):
        self.db = db
        self.repository = repository
        self.profile = profile

    async def _read_only_snapshot(self, limits: HistoricalAnalyticsLimits) -> None:
        await self.db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        await self.db.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{int(limits.max_query_seconds * 1000)}ms"},
        )

    async def analyze_asset(self, *, client_id: int, asset_id: int,
                            window_start: datetime, window_end: datetime,
                            grid_config: SpatialGridConfig,
                            assessment_config: SpatialAssessmentConfig = SpatialAssessmentConfig(),
                            limits: HistoricalAnalyticsLimits = HistoricalAnalyticsLimits()) -> HistoricalSpatialAnalyticsResult:
        return await self.analyze_assets(
            client_id=client_id, asset_ids=(asset_id,), window_start=window_start,
            window_end=window_end, grid_config=grid_config,
            assessment_config=assessment_config, limits=limits,
        )

    async def analyze_asset_group(self, *, client_id: int, group_id: int,
                                  window_start: datetime, window_end: datetime,
                                  grid_config: SpatialGridConfig,
                                  assessment_config: SpatialAssessmentConfig = SpatialAssessmentConfig(),
                                  limits: HistoricalAnalyticsLimits = HistoricalAnalyticsLimits()) -> HistoricalSpatialAnalyticsResult:
        self._validate_id(client_id)
        self._validate_id(group_id)
        repository = self.repository or HistoricalSpatialAnalyticsRepository(self.db)
        if self.repository is None:
            if self.db.in_transaction():
                raise HistoricalAnalyticsError("Analytics needs a fresh read-only database transaction.")
            async with self.db.begin():
                await self._read_only_snapshot(limits)
                ids = await repository.group_asset_ids(client_id=client_id, group_id=group_id,
                                                       limit=limits.max_assets + 1)
                if ids is None:
                    raise HistoricalAnalyticsNotFound("Asset group not found.")
                return await self._analyze(repository, client_id=client_id, asset_ids=ids,
                                           window_start=window_start, window_end=window_end,
                                           grid_config=grid_config, assessment_config=assessment_config, limits=limits)
        ids = await repository.group_asset_ids(client_id=client_id, group_id=group_id,
                                               limit=limits.max_assets + 1)
        if ids is None:
            raise HistoricalAnalyticsNotFound("Asset group not found.")
        return await self._analyze(repository, client_id=client_id, asset_ids=ids,
                                   window_start=window_start, window_end=window_end,
                                   grid_config=grid_config, assessment_config=assessment_config, limits=limits)

    async def analyze_assets(self, *, client_id: int, asset_ids: Sequence[int],
                             window_start: datetime, window_end: datetime,
                             grid_config: SpatialGridConfig,
                             assessment_config: SpatialAssessmentConfig = SpatialAssessmentConfig(),
                             limits: HistoricalAnalyticsLimits = HistoricalAnalyticsLimits()) -> HistoricalSpatialAnalyticsResult:
        repository = self.repository or HistoricalSpatialAnalyticsRepository(self.db)
        if self.repository is None:
            if self.db.in_transaction():
                raise HistoricalAnalyticsError("Analytics needs a fresh read-only database transaction.")
            async with self.db.begin():
                await self._read_only_snapshot(limits)
                return await self._analyze(repository, client_id=client_id, asset_ids=asset_ids,
                                           window_start=window_start, window_end=window_end,
                                           grid_config=grid_config, assessment_config=assessment_config, limits=limits)
        return await self._analyze(repository, client_id=client_id, asset_ids=asset_ids,
                                   window_start=window_start, window_end=window_end,
                                   grid_config=grid_config, assessment_config=assessment_config, limits=limits)

    @staticmethod
    def _validate_id(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise HistoricalAnalyticsError("IDs must be positive integers.")

    async def _analyze(self, repository: HistoricalSpatialAnalyticsRepository, *, client_id: int,
                       asset_ids: Sequence[int], window_start: datetime, window_end: datetime,
                       grid_config: SpatialGridConfig, assessment_config: SpatialAssessmentConfig,
                       limits: HistoricalAnalyticsLimits) -> HistoricalSpatialAnalyticsResult:
        profile = self.profile
        if profile is not None:
            profile.reset()
            if isinstance(repository, HistoricalSpatialAnalyticsRepository):
                repository.profile = profile
        started = perf_counter() if profile is not None else 0.0
        self._validate_id(client_id)
        if (
            not isinstance(window_start, datetime) or not isinstance(window_end, datetime)
            or window_start.tzinfo is not None or window_end.tzinfo is not None
            or window_start >= window_end or not isinstance(grid_config, SpatialGridConfig)
            or not isinstance(assessment_config, SpatialAssessmentConfig)
            or not isinstance(limits, HistoricalAnalyticsLimits)
        ):
            raise HistoricalAnalyticsError("Invalid analytics window or configuration.")
        if len(asset_ids) > limits.max_assets:
            raise HistoricalAnalyticsLimitExceeded("Asset limit exceeded.")
        ids = tuple(sorted(set(asset_ids)))
        for asset_id in ids:
            self._validate_id(asset_id)
        if len(ids) > limits.max_assets:
            raise HistoricalAnalyticsLimitExceeded("Asset limit exceeded.")
        assignment_started = perf_counter() if profile is not None else 0.0
        if await repository.accessible_asset_ids(client_id=client_id, asset_ids=ids) != set(ids):
            raise HistoricalAnalyticsNotFound("Asset not found.")
        try:
            history = await repository.assignments(client_id=client_id, asset_ids=ids,
                                                   window_start=window_start, window_end=window_end,
                                                   limit=limits.max_assignments + 1)
        except HistoricalRepositoryLimitExceeded as exc:
            raise HistoricalAnalyticsLimitExceeded("Assignment limit exceeded.") from exc
        if len(history) >= limits.max_assignments + 1:
            raise HistoricalAnalyticsLimitExceeded("Assignment limit exceeded.")
        estimate_locations = getattr(repository, "estimate_location_count", None)
        if estimate_locations is not None:
            estimated_count = await estimate_locations(
                client_id=client_id,
                asset_ids=ids,
                window_start=window_start,
                window_end=window_end,
                limit=limits.max_locations + 1,
            )
            if estimated_count > limits.max_locations:
                raise HistoricalAnalyticsLimitExceeded("Estimated location limit exceeded.")
        coverage = resolve_assignment_windows(history, window_start=window_start, window_end=window_end)
        selected = tuple(w for w in coverage.windows if w.assignment.asset_id in ids)
        eligible_duration = sum((w.end_at - w.start_at for w in selected), timedelta())
        device_ids = {w.assignment.device_id for w in selected}
        resolution = calculate_bucket_resolution(
            window_seconds=(window_end - window_start).total_seconds(), device_count=len(device_ids)
        )
        if profile is not None:
            profile.assignment_seconds += max(0.0, perf_counter() - assignment_started
                - profile.sql_execute_seconds - profile.row_materialization_seconds)
        totals = _Totals()
        deadline = monotonic() + limits.max_query_seconds
        for window in selected:
            await self._process_assignment(
                repository, window.assignment, window_start, window_end,
                resolution.bucket_seconds, grid_config, assessment_config, limits, totals, deadline, profile,
            )
        if totals.assessed > eligible_duration:
            raise HistoricalAnalyticsError("Assessed seconds exceed known assignment time.")
        if totals.observed != totals.eligible + totals.displaced + totals.uncertain:
            raise HistoricalAnalyticsError("Spatial classification does not conserve observed time.")
        if totals.eligible != totals.dwell + totals.excluded:
            raise HistoricalAnalyticsError("Spatial aggregation does not conserve eligible time.")
        buckets = tuple(
            SpatialTemporalBucket(asset_id, bucket_start, source.bucket_end, cell_id, source.cell,
                                  duration.total_seconds(), count, None)
            for (asset_id, bucket_start, cell_id), (source, duration, count, _last)
            in sorted(totals.cells.items())
        )
        result = HistoricalSpatialAnalyticsResult(buckets, HistoricalSpatialAnalyticsMetadata(
            window_start, window_end, (window_end - window_start).total_seconds() * len(ids),
            eligible_duration.total_seconds(), totals.assessed.total_seconds(),
            (eligible_duration - totals.assessed).total_seconds(),
            totals.observed.total_seconds(), totals.gap.total_seconds(),
            totals.indeterminate.total_seconds(), (totals.gap + totals.indeterminate).total_seconds(),
            totals.eligible.total_seconds(), totals.displaced.total_seconds(),
            totals.uncertain.total_seconds(), totals.excluded.total_seconds(),
            totals.boundary.total_seconds(), totals.outside.total_seconds(),
            totals.dwell.total_seconds(),
            temporal_coverage_ratio(totals.observed.total_seconds(), eligible_duration.total_seconds()),
            totals.raw_count, totals.eligible_count, totals.processed_count,
            len(device_ids), len(ids), resolution.bucket_seconds, grid_config.cell_size_meters,
            grid_config.crs,
        ))
        if profile is not None:
            profile.locations_processed = totals.processed_count
            profile.fragments_created = totals.fragments
            profile.result_count = len(buckets)
            profile.cell_count = len(totals.cell_ids)
            profile.finish(perf_counter() - started)
        return result

    async def _process_assignment(self, repository: HistoricalSpatialAnalyticsRepository,
                                  assignment: AssignmentRef, window_start: datetime, window_end: datetime,
                                  bucket_seconds: int, grid_config: SpatialGridConfig,
                                  assessment_config: SpatialAssessmentConfig,
                                  limits: HistoricalAnalyticsLimits, totals: _Totals,
                                  deadline: float, profile: ProcessingProfile | None) -> None:
        analyzer = RollingTemporalAnalyzer(profile=profile)
        async def ingest(obs: SpatialObservationRef, *, inside: bool) -> None:
            if monotonic() > deadline:
                raise HistoricalAnalyticsLimitExceeded("Analytics processing time limit exceeded.")
            totals.processed_count += 1
            if totals.processed_count > limits.max_locations:
                raise HistoricalAnalyticsLimitExceeded("Processed location limit exceeded.")
            if inside:
                totals.raw_count += 1
                if (
                    isinstance(obs.latitude, (int, float)) and not isinstance(obs.latitude, bool)
                    and isinstance(obs.longitude, (int, float)) and not isinstance(obs.longitude, bool)
                    and isfinite(obs.latitude) and isfinite(obs.longitude)
                    and -90 <= obs.latitude <= 90 and -180 <= obs.longitude <= 180
                    and isinstance(obs.accuracy_meters, (int, float))
                    and not isinstance(obs.accuracy_meters, bool)
                    and isfinite(obs.accuracy_meters)
                    and 0 <= obs.accuracy_meters < assessment_config.max_usable_accuracy_meters
                ):
                    totals.eligible_count += 1
            for left, right, temporal in analyzer.feed(obs):
                self._process_interval(left, right, temporal, assignment.asset_id, window_start,
                                       window_end, bucket_seconds, grid_config, assessment_config,
                                        limits, totals, profile)

        for obs in await repository.neighboring_locations(assignment, boundary=window_start, before=True):
            await ingest(obs, inside=False)
        async for obs in repository.iter_locations(assignment, start=window_start, end=window_end,
                                                    page_size=limits.page_size):
            await ingest(obs, inside=True)
        for obs in await repository.neighboring_locations(assignment, boundary=window_end, before=False):
            await ingest(obs, inside=False)
        for left, right, temporal in analyzer.finish():
            self._process_interval(left, right, temporal, assignment.asset_id, window_start,
                                   window_end, bucket_seconds, grid_config, assessment_config,
                                   limits, totals, profile)

    @staticmethod
    def _process_interval(left: SpatialObservationRef, right: SpatialObservationRef,
                          temporal, asset_id: int, window_start: datetime, window_end: datetime,
                           bucket_seconds: int, grid_config: SpatialGridConfig,
                           assessment_config: SpatialAssessmentConfig,
                           limits: HistoricalAnalyticsLimits, totals: _Totals,
                           profile: ProcessingProfile | None) -> None:
        start = max(window_start, temporal.start_at)
        end = min(window_end, temporal.end_at)
        if start >= end:
            return
        duration = end - start
        totals.assessed += duration
        stage_started = perf_counter() if profile is not None else 0.0
        measured = calculate_observed_time((temporal,)).metadata
        if profile is not None:
            profile.observed_time_seconds += perf_counter() - stage_started
        if temporal.status == ContinuityStatus.GAP:
            totals.gap += duration
            return
        if temporal.status == ContinuityStatus.INDETERMINATE:
            totals.indeterminate += duration
            return
        if measured.observed_seconds != temporal.delta_seconds:
            raise HistoricalAnalyticsError("Observed interval invariant failed.")
        # Each half can intersect two+ buckets. Refuse large fanout before
        # materializing fragments, even when temporal point estimates fit.
        projected_fragments = 2 * (int(duration.total_seconds() // bucket_seconds) + 3)
        if totals.fragments + projected_fragments > limits.max_fragments:
            raise HistoricalAnalyticsLimitExceeded("Temporal fragment limit exceeded.")
        refs = (TemporalObservationRef(left.observation_id, left.observed_at),
                TemporalObservationRef(right.observation_id, right.observed_at))
        stage_started = perf_counter() if profile is not None else 0.0
        attribution = attribute_observed_time_to_observations(refs, (temporal,))
        if profile is not None:
            profile.attribution_seconds += perf_counter() - stage_started
        stage_started = perf_counter() if profile is not None else 0.0
        bucketed = bucket_observation_contributions(
            contributions=attribution.contributions, window_start=window_start,
            window_end=window_end, bucket_seconds=bucket_seconds,
        )
        if profile is not None:
            profile.bucketing_seconds += perf_counter() - stage_started
        totals.fragments += len(bucketed.contributions)
        stage_started = perf_counter() if profile is not None else 0.0
        spatial = assess_spatial_interval(left, right, temporal, config=assessment_config)
        if profile is not None:
            profile.spatial_assessment_seconds += perf_counter() - stage_started
        stage_started = perf_counter() if profile is not None else 0.0
        qualified = _qualify_generated_interval(
            contributions=bucketed.contributions, temporal=temporal, spatial=spatial,
            window_start=window_start, window_end=window_end,
        )
        if profile is not None:
            profile.qualification_seconds += perf_counter() - stage_started
        # With no eligible time there is no cell to build. Qualification already
        # classified and conserved the entire interval; aggregating an empty
        # result cannot add information and was a measured hot path at 15min.
        if qualified.metadata.spatially_eligible_seconds == 0:
            totals.observed += duration
            totals.displaced += timedelta(seconds=qualified.metadata.displacement_seconds)
            totals.uncertain += timedelta(seconds=qualified.metadata.spatially_uncertain_seconds)
            return
        stage_started = perf_counter() if profile is not None else 0.0
        previous_grid_seconds = profile.grid_seconds if profile is not None else 0.0
        aggregated = aggregate_spatial_time(
            asset_id=asset_id, qualified=qualified,
            observations={left.observation_id: left, right.observation_id: right},
            config=grid_config, max_cells=limits.max_cells, profile=profile,
        )
        if profile is not None:
            profile.aggregation_seconds += max(0.0, perf_counter() - stage_started
                - (profile.grid_seconds - previous_grid_seconds))
        metadata = aggregated.metadata
        totals.observed += duration
        totals.eligible += timedelta(seconds=qualified.metadata.spatially_eligible_seconds)
        totals.displaced += timedelta(seconds=qualified.metadata.displacement_seconds)
        totals.uncertain += timedelta(seconds=qualified.metadata.spatially_uncertain_seconds)
        totals.excluded += timedelta(seconds=metadata.other_excluded_seconds)
        totals.boundary += timedelta(seconds=metadata.cell_boundary_uncertain_seconds)
        totals.outside += timedelta(seconds=metadata.outside_grid_seconds)
        totals.dwell += timedelta(seconds=metadata.dwell_seconds)
        for item in aggregated.buckets:
            key = item.asset_id, item.bucket_start, item.spatial_cell_id
            if item.spatial_cell_id not in totals.cell_ids and len(totals.cell_ids) >= limits.max_cells:
                raise HistoricalAnalyticsLimitExceeded("Spatial cell limit exceeded.")
            if key not in totals.cells and len(totals.cells) >= limits.max_results:
                raise HistoricalAnalyticsLimitExceeded("Spatial result limit exceeded.")
            totals.cell_ids.add(item.spatial_cell_id)
            previous, seconds, count, last_id = totals.cells.get(key, (item, timedelta(), 0, None))
            for observation_id in item.observation_ids:
                if observation_id != last_id:
                    count += 1
                    last_id = observation_id
            totals.cells[key] = previous, seconds + timedelta(seconds=item.dwell_seconds), count, last_id
