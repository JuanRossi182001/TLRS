"""Accumulate qualified animal-seconds in fixed metric cells, without averaging."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from time import perf_counter
from typing import Mapping, Sequence

from src.application.analytics.spatial_assessment import SpatialObservationRef, SpatialIntervalStatus
from src.application.analytics.performance_profile import ProcessingProfile
from src.application.analytics.spatial_grid import (
    SpatialCell, SpatialGridConfig, SpatialGridInputError, _project_cached_cell,
)
from src.application.analytics.spatial_qualification import SpatialQualificationResult, SpatiallyQualifiedContribution


class SpatialAggregationInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SpatialTemporalBucket:
    asset_id: int
    bucket_start: datetime
    bucket_end: datetime
    spatial_cell_id: str
    cell: SpatialCell
    dwell_seconds: float
    observation_count: int
    # Present for a single interval's intermediate result. Final, bounded
    # multi-interval results omit the ID list (None) and retain the count.
    observation_ids: tuple[int, ...] | None


@dataclass(frozen=True, slots=True)
class SpatialAggregationMetadata:
    observed_seconds: float
    dwell_seconds: float
    displacement_seconds: float
    spatially_uncertain_seconds: float
    other_excluded_seconds: float
    cell_boundary_uncertain_seconds: float
    outside_grid_seconds: float


@dataclass(frozen=True, slots=True)
class SpatialAggregationResult:
    buckets: tuple[SpatialTemporalBucket, ...]
    metadata: SpatialAggregationMetadata


def aggregate_spatial_time(
    *, asset_id: int, qualified: SpatialQualificationResult,
    observations: Mapping[int, SpatialObservationRef], config: SpatialGridConfig,
    max_cells: int = 25_000,
    profile: ProcessingProfile | None = None,
) -> SpatialAggregationResult:
    """Assign only unambiguous GPS fixes to cells, preserving excluded seconds.

    Accuracy is a reported radius, not a statistical guarantee. A 1.001 factor
    conservatively accounts for local UTM scale (within the CRS area of use).
    """
    if (
        isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id <= 0
        or not isinstance(qualified, SpatialQualificationResult)
        or not isinstance(config, SpatialGridConfig)
        or isinstance(max_cells, bool) or not isinstance(max_cells, int) or max_cells <= 0
    ):
        raise SpatialAggregationInputError("Invalid asset, qualification, grid or cell limit.")
    grouped: dict[tuple[datetime, str], tuple[SpatialCell, timedelta, set[int], datetime]] = {}
    dwell = timedelta()
    boundary = timedelta()
    outside = timedelta()
    eligible = timedelta()
    displaced = timedelta()
    uncertain = timedelta()
    for item in qualified.contributions:
        if not isinstance(item, SpatiallyQualifiedContribution):
            raise SpatialAggregationInputError("Invalid qualified contribution.")
        part = item.source
        duration = part.contribution_end - part.contribution_start
        if duration <= timedelta() or duration.total_seconds() != part.observed_seconds:
            raise SpatialAggregationInputError("Invalid contribution duration.")
        if item.eligible_for_dwell != (item.spatial_status == SpatialIntervalStatus.STATIONARY_COMPATIBLE):
            raise SpatialAggregationInputError("Inconsistent spatial qualification.")
        if item.spatial_status == SpatialIntervalStatus.DISPLACEMENT:
            displaced += duration
            continue
        if item.spatial_status == SpatialIntervalStatus.SPATIALLY_UNCERTAIN:
            uncertain += duration
            continue
        if item.spatial_status != SpatialIntervalStatus.STATIONARY_COMPATIBLE or not item.eligible_for_dwell:
            raise SpatialAggregationInputError("Inconsistent spatial qualification.")
        eligible += duration
        observation = observations.get(part.observation_id)
        if not isinstance(observation, SpatialObservationRef) or observation.observation_id != part.observation_id:
            raise SpatialAggregationInputError("Missing source observation.")
        if (
            isinstance(observation.accuracy_meters, bool)
            or not isinstance(observation.accuracy_meters, (int, float))
            or not isfinite(observation.accuracy_meters)
            or observation.accuracy_meters < 0
        ):
            raise SpatialAggregationInputError("Eligible observation needs a valid accuracy.")
        grid_started = perf_counter() if profile is not None else 0.0
        try:
            cell, x, y = _project_cached_cell(
                latitude=observation.latitude, longitude=observation.longitude, config=config,
            )
        except SpatialGridInputError as exc:
            if "outside the configured CRS area of use" not in str(exc):
                raise SpatialAggregationInputError("Eligible coordinate cannot be mapped to the grid.") from exc
            outside += duration
            continue
        finally:
            if profile is not None:
                profile.grid_seconds += perf_counter() - grid_started
        radius = observation.accuracy_meters * 1.001
        if min(x - cell.x_min, cell.x_max - x, y - cell.y_min, cell.y_max - y) <= radius:
            boundary += duration
            continue
        key = part.bucket_start, cell.cell_id
        if key not in grouped and len(grouped) >= max_cells:
            raise SpatialAggregationInputError("Spatial cell result limit exceeded.")
        if key not in grouped:
            grouped[key] = (cell, timedelta(), set(), part.bucket_end)
        existing, seconds, ids, bucket_end = grouped[key]
        if bucket_end != part.bucket_end:
            raise SpatialAggregationInputError("Inconsistent bucket boundaries.")
        ids.add(part.observation_id)
        grouped[key] = (existing, seconds + duration, ids, bucket_end)
        dwell += duration
    if eligible != dwell + boundary + outside:
        raise SpatialAggregationInputError("Spatially eligible time was not conserved.")
    observed = dwell + boundary + outside + displaced + uncertain
    if observed.total_seconds() != qualified.metadata.observed_seconds:
        raise SpatialAggregationInputError("Observed time differs from qualification metadata.")
    buckets = tuple(
        SpatialTemporalBucket(
            asset_id, start, end, cell_id, cell, seconds.total_seconds(), len(ids),
            tuple(sorted(ids, key=lambda observation_id: (
                observations[observation_id].observed_at, observation_id,
            ))),
        )
        for (start, cell_id), (cell, seconds, ids, end) in sorted(grouped.items())
    )
    return SpatialAggregationResult(buckets, SpatialAggregationMetadata(
        observed.total_seconds(), dwell.total_seconds(), displaced.total_seconds(),
        uncertain.total_seconds(), (boundary + outside).total_seconds(),
        boundary.total_seconds(), outside.total_seconds(),
    ))
