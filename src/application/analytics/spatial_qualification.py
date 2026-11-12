"""Classify already-bucketed observed time by interval-level spatial evidence."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from src.application.analytics.observation_attribution import ContributionSide
from src.application.analytics.observation_bucketing import ObservationBucketContribution
from src.application.analytics.spatial_assessment import (
    SpatialIntervalAssessment, SpatialIntervalStatus, SpatialAssessmentReason,
)
from src.application.analytics.temporal_continuity import ContinuityStatus, TemporalIntervalAssessment


class SpatialQualificationInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SpatiallyQualifiedContribution:
    source: ObservationBucketContribution
    spatial_status: SpatialIntervalStatus
    reason: SpatialAssessmentReason
    eligible_for_dwell: bool


@dataclass(frozen=True, slots=True)
class SpatialQualificationMetadata:
    observed_seconds: float
    spatially_eligible_seconds: float
    displacement_seconds: float
    spatially_uncertain_seconds: float


@dataclass(frozen=True, slots=True)
class SpatialQualificationResult:
    contributions: tuple[SpatiallyQualifiedContribution, ...]
    metadata: SpatialQualificationMetadata


def _qualify_generated_interval(
    *, contributions: Sequence[ObservationBucketContribution],
    temporal: TemporalIntervalAssessment, spatial: SpatialIntervalAssessment,
    window_start: datetime, window_end: datetime,
) -> SpatialQualificationResult:
    """Internal fast path for one interval from 1A.6 + 1A.7; keep public validator.

    Service owns the validated inputs from these functions. Enforce conservation
    and identity here; no dicts, per-piece status summation or re-sorting.
    """
    if (
        temporal.status != ContinuityStatus.CONTINUOUS
        or spatial.interval_start != temporal.start_at
        or spatial.interval_end != temporal.end_at
        or spatial.elapsed_seconds != temporal.delta_seconds
    ):
        raise SpatialQualificationInputError("Generated interval does not match its spatial assessment.")
    start = max(window_start, temporal.start_at)
    end = min(window_end, temporal.end_at)
    expected = end - start
    if expected <= timedelta():
        raise SpatialQualificationInputError("Generated interval must intersect the window.")
    status = spatial.status
    if status not in SpatialIntervalStatus:
        raise SpatialQualificationInputError("Unsupported spatial status.")
    eligible = status == SpatialIntervalStatus.STATIONARY_COMPATIBLE
    cursor = start
    output: list[SpatiallyQualifiedContribution] = []
    midpoint = temporal.start_at + (temporal.end_at - temporal.start_at) / 2
    for piece in contributions:
        expected_id = spatial.left_observation_id if piece.side == ContributionSide.LEFT else spatial.right_observation_id
        if (
            piece.interval_index != 0
            or piece.observation_id != expected_id
            or piece.contribution_start != cursor
            or piece.contribution_end <= cursor
            or piece.contribution_end > end
            or (piece.side == ContributionSide.LEFT and piece.contribution_end > midpoint)
            or (piece.side == ContributionSide.RIGHT and cursor < midpoint)
        ):
            raise SpatialQualificationInputError("Invalid generated observation fragment.")
        output.append(SpatiallyQualifiedContribution(piece, status, spatial.reason, eligible))
        cursor = piece.contribution_end
    if cursor != end:
        raise SpatialQualificationInputError("Generated fragments do not conserve the interval.")
    seconds = expected.total_seconds()
    return SpatialQualificationResult(
        tuple(output), SpatialQualificationMetadata(
            seconds, seconds if eligible else 0.0,
            seconds if status == SpatialIntervalStatus.DISPLACEMENT else 0.0,
            seconds if status == SpatialIntervalStatus.SPATIALLY_UNCERTAIN else 0.0,
        ),
    )


def qualify_observed_time(
    *, contributions: Sequence[ObservationBucketContribution],
    temporal: Sequence[TemporalIntervalAssessment],
    spatial: Sequence[SpatialIntervalAssessment],
    window_start: datetime, window_end: datetime,
) -> SpatialQualificationResult:
    """Retain all observed time; reject missing, repeated or inconsistent fragments."""
    if (
        not isinstance(window_start, datetime) or not isinstance(window_end, datetime)
        or window_start.tzinfo is not None or window_end.tzinfo is not None
        or window_end <= window_start or len(temporal) != len(spatial)
    ):
        raise SpatialQualificationInputError("Invalid window or interval assessment counts.")
    coverage: dict[int, timedelta] = {}
    output: list[SpatiallyQualifiedContribution] = []
    observed = timedelta()
    eligible = timedelta()
    displaced = timedelta()
    uncertain = timedelta()
    previous_end_by_side: dict[tuple[int, ContributionSide], datetime] = {}
    ranges: dict[int, list[tuple[datetime, datetime]]] = {}
    for index, (time, space) in enumerate(zip(temporal, spatial)):
        if (
            not isinstance(time, TemporalIntervalAssessment)
            or not isinstance(space, SpatialIntervalAssessment)
            or time.start_at != space.interval_start or time.end_at != space.interval_end
            or time.delta_seconds != space.elapsed_seconds
        ):
            raise SpatialQualificationInputError(f"Spatial assessment at index {index} does not match temporal interval.")
    for item in contributions:
        if not isinstance(item, ObservationBucketContribution) or not 0 <= item.interval_index < len(temporal):
            raise SpatialQualificationInputError("Unknown source contribution interval.")
        time = temporal[item.interval_index]
        space = spatial[item.interval_index]
        if time.status != ContinuityStatus.CONTINUOUS:
            raise SpatialQualificationInputError("Only continuous intervals can contribute observed time.")
        midpoint = time.start_at + (time.end_at - time.start_at) / 2
        expected_id = space.left_observation_id if item.side == ContributionSide.LEFT else space.right_observation_id
        if (
            item.side not in (ContributionSide.LEFT, ContributionSide.RIGHT)
            or item.observation_id != expected_id
            or (item.side == ContributionSide.LEFT and item.contribution_end > midpoint)
            or (item.side == ContributionSide.RIGHT and item.contribution_start < midpoint)
            or not (time.start_at <= item.contribution_start < item.contribution_end <= time.end_at)
            or not (item.bucket_start <= item.contribution_start < item.contribution_end <= item.bucket_end)
            or not (window_start <= item.contribution_start < item.contribution_end <= window_end)
            or item.observed_seconds != (item.contribution_end - item.contribution_start).total_seconds()
        ):
            raise SpatialQualificationInputError("Invalid contribution bounds, duration, side or observation ID.")
        key = item.interval_index, item.side
        if key in previous_end_by_side and item.contribution_start < previous_end_by_side[key]:
            raise SpatialQualificationInputError("Overlapping source fragments.")
        previous_end_by_side[key] = item.contribution_end
        duration = item.contribution_end - item.contribution_start
        coverage[item.interval_index] = coverage.get(item.interval_index, timedelta()) + duration
        ranges.setdefault(item.interval_index, []).append((item.contribution_start, item.contribution_end))
        observed += duration
        if space.status == SpatialIntervalStatus.STATIONARY_COMPATIBLE:
            eligible += duration
        elif space.status == SpatialIntervalStatus.DISPLACEMENT:
            displaced += duration
        elif space.status == SpatialIntervalStatus.SPATIALLY_UNCERTAIN:
            uncertain += duration
        else:
            raise SpatialQualificationInputError("Unsupported spatial status.")
        output.append(SpatiallyQualifiedContribution(
            item, space.status, space.reason,
            space.status == SpatialIntervalStatus.STATIONARY_COMPATIBLE,
        ))
    for index, item in enumerate(temporal):
        clipped = max(
            min(item.end_at, window_end) - max(item.start_at, window_start), timedelta()
        ) if item.status == ContinuityStatus.CONTINUOUS else timedelta()
        if coverage.get(index, timedelta()) != clipped:
            raise SpatialQualificationInputError(f"Observed time is missing or duplicated at interval {index}.")
        if clipped:
            cursor = max(item.start_at, window_start)
            for start, end in sorted(ranges.get(index, [])):
                if start != cursor:
                    raise SpatialQualificationInputError(f"Non-contiguous or overlapping fragments at interval {index}.")
                cursor = end
            if cursor != min(item.end_at, window_end):
                raise SpatialQualificationInputError(f"Incomplete fragments at interval {index}.")
    return SpatialQualificationResult(tuple(output), SpatialQualificationMetadata(
        observed.total_seconds(), eligible.total_seconds(), displaced.total_seconds(),
        uncertain.total_seconds(),
    ))
