"""Conservative, auditable evidence of spatial dwell between GPS observations."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from pyproj import Geod

from src.application.analytics.temporal_continuity import (
    ContinuityStatus,
    TemporalIntervalAssessment,
)


class SpatialAssessmentInputError(ValueError):
    pass


class SpatialIntervalStatus(str, Enum):
    STATIONARY_COMPATIBLE = "stationary_compatible"
    DISPLACEMENT = "displacement"
    SPATIALLY_UNCERTAIN = "spatially_uncertain"


class SpatialAssessmentReason(str, Enum):
    COMPATIBLE = "compatible"
    DISPLACEMENT = "displacement"
    TEMPORALLY_UNCERTAIN = "temporally_uncertain"
    INSUFFICIENT_ACCURACY = "insufficient_accuracy"
    INVALID_COORDINATE = "invalid_coordinate"
    LONG_INTERVAL = "long_interval"
    IMPLAUSIBLE_JUMP = "implausible_jump"
    AMBIGUOUS_POSITION = "ambiguous_position"


@dataclass(frozen=True, slots=True)
class SpatialObservationRef:
    observation_id: int
    observed_at: datetime
    latitude: float | None
    longitude: float | None
    accuracy_meters: float | None


@dataclass(frozen=True, slots=True)
class SpatialAssessmentConfig:
    max_usable_accuracy_meters: float = 30.0
    max_stationary_displacement_meters: float = 10.0
    max_stationary_extent_meters: float = 25.0
    max_stationary_evidence_interval_seconds: float = 60.0
    max_plausible_speed_mps: float = 8.0

    def __post_init__(self) -> None:
        for name, value in vars_by_fields(self):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise SpatialAssessmentInputError(f"{name} must be finite and positive.")


def vars_by_fields(config: SpatialAssessmentConfig) -> tuple[tuple[str, float], ...]:
    return tuple((name, getattr(config, name)) for name in config.__dataclass_fields__)


@dataclass(frozen=True, slots=True)
class SpatialIntervalAssessment:
    left_observation_id: int
    right_observation_id: int
    interval_start: datetime
    interval_end: datetime
    distance_meters: float | None
    elapsed_seconds: float
    apparent_speed_mps: float | None
    minimum_separation_meters: float | None
    left_accuracy_meters: float | None
    right_accuracy_meters: float | None
    status: SpatialIntervalStatus
    reason: SpatialAssessmentReason


_GEOD = Geod(ellps="WGS84")


def _usable_coordinate(value: float | None, lower: float, upper: float) -> bool:
    return (
        not isinstance(value, bool) and isinstance(value, (int, float))
        and isfinite(value) and lower <= value <= upper
    )


def _usable_accuracy(value: float | None, maximum: float) -> bool:
    return (
        not isinstance(value, bool) and isinstance(value, (int, float))
        and isfinite(value) and 0 <= value < maximum
    )


def assess_spatial_interval(
    left: SpatialObservationRef,
    right: SpatialObservationRef,
    temporal: TemporalIntervalAssessment,
    *,
    config: SpatialAssessmentConfig = SpatialAssessmentConfig(),
) -> SpatialIntervalAssessment:
    """Use both GPS endpoints and temporal evidence; invalid fixes remain uncertain."""
    if not isinstance(config, SpatialAssessmentConfig) or not all(
        isinstance(o, SpatialObservationRef) for o in (left, right)
    ) or not isinstance(temporal, TemporalIntervalAssessment):
        raise SpatialAssessmentInputError("Invalid spatial assessment inputs.")
    for observation in (left, right):
        if (
            isinstance(observation.observation_id, bool)
            or not isinstance(observation.observation_id, int)
            or observation.observation_id <= 0
            or not isinstance(observation.observed_at, datetime)
            or observation.observed_at.tzinfo is not None
        ):
            raise SpatialAssessmentInputError("Invalid observation identity or UTC-naive timestamp.")
    if (
        left.observation_id == right.observation_id
        or left.observed_at != temporal.start_at
        or right.observed_at != temporal.end_at
        or not isinstance(temporal.start_at, datetime)
        or not isinstance(temporal.end_at, datetime)
        or temporal.start_at.tzinfo is not None
        or temporal.end_at.tzinfo is not None
        or right.observed_at < left.observed_at
        or temporal.delta_seconds != (right.observed_at - left.observed_at).total_seconds()
        or not isinstance(temporal.status, ContinuityStatus)
    ):
        raise SpatialAssessmentInputError("Spatial and temporal intervals must match.")
    elapsed = temporal.delta_seconds
    distance: float | None = None
    speed: float | None = None
    minimum: float | None = None
    if temporal.status != ContinuityStatus.CONTINUOUS or elapsed == 0:
        reason = SpatialAssessmentReason.TEMPORALLY_UNCERTAIN
    elif not all((
        _usable_coordinate(left.latitude, -90, 90),
        _usable_coordinate(left.longitude, -180, 180),
        _usable_coordinate(right.latitude, -90, 90),
        _usable_coordinate(right.longitude, -180, 180),
    )):
        reason = SpatialAssessmentReason.INVALID_COORDINATE
    elif not (
        _usable_accuracy(left.accuracy_meters, config.max_usable_accuracy_meters)
        and _usable_accuracy(right.accuracy_meters, config.max_usable_accuracy_meters)
    ):
        reason = SpatialAssessmentReason.INSUFFICIENT_ACCURACY
    else:
        _, _, distance = _GEOD.inv(left.longitude, left.latitude, right.longitude, right.latitude)
        if not isfinite(distance):
            distance = None
            reason = SpatialAssessmentReason.INVALID_COORDINATE
        else:
            speed = distance / elapsed
            minimum = max(0.0, distance - left.accuracy_meters - right.accuracy_meters)
            if minimum / elapsed > config.max_plausible_speed_mps:
                reason = SpatialAssessmentReason.IMPLAUSIBLE_JUMP
            elif minimum > config.max_stationary_displacement_meters:
                reason = SpatialAssessmentReason.DISPLACEMENT
            elif elapsed > config.max_stationary_evidence_interval_seconds:
                reason = SpatialAssessmentReason.LONG_INTERVAL
            elif (
                distance + left.accuracy_meters + right.accuracy_meters
                > config.max_stationary_extent_meters
            ):
                reason = SpatialAssessmentReason.AMBIGUOUS_POSITION
            else:
                reason = SpatialAssessmentReason.COMPATIBLE

    status = (
        SpatialIntervalStatus.STATIONARY_COMPATIBLE if reason == SpatialAssessmentReason.COMPATIBLE
        else SpatialIntervalStatus.DISPLACEMENT if reason == SpatialAssessmentReason.DISPLACEMENT
        else SpatialIntervalStatus.SPATIALLY_UNCERTAIN
    )
    return SpatialIntervalAssessment(
        left.observation_id, right.observation_id, left.observed_at, right.observed_at,
        distance, elapsed, speed, minimum, left.accuracy_meters,
        right.accuracy_meters, status, reason,
    )
