from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from statistics import median
from typing import Sequence


DEFAULT_CADENCE_WINDOW_SIZE = 4
DEFAULT_MIN_CADENCE_SAMPLES = 3
DEFAULT_GAP_FACTOR = 3.0
DEFAULT_MIN_JITTER_ALLOWANCE_SECONDS = 5.0
DEFAULT_MAX_CADENCE_VARIABILITY = 0.25


class ContinuityStatus(str, Enum):
    CONTINUOUS = "continuous"
    GAP = "gap"
    INDETERMINATE = "indeterminate"


class CadenceSource(str, Enum):
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"


class TemporalContinuityInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TemporalIntervalAssessment:
    start_at: datetime
    end_at: datetime
    delta_seconds: float
    status: ContinuityStatus
    cadence_source: CadenceSource
    left_expected_interval_seconds: float | None
    right_expected_interval_seconds: float | None
    left_continuity_threshold_seconds: float | None
    right_continuity_threshold_seconds: float | None


@dataclass(frozen=True, slots=True)
class _CadenceEstimate:
    expected_interval_seconds: float
    continuity_threshold_seconds: float


def analyze_temporal_continuity(
    observed_timestamps: Sequence[datetime],
    *,
    cadence_window_size: int = DEFAULT_CADENCE_WINDOW_SIZE,
    min_cadence_samples: int = DEFAULT_MIN_CADENCE_SAMPLES,
    gap_factor: float = DEFAULT_GAP_FACTOR,
    min_jitter_allowance_seconds: float = DEFAULT_MIN_JITTER_ALLOWANCE_SECONDS,
    max_cadence_variability: float = DEFAULT_MAX_CADENCE_VARIABILITY,
) -> tuple[TemporalIntervalAssessment, ...]:
    """Classify consecutive UTC-naive timestamps using local cadence evidence."""
    _validate_configuration(
        cadence_window_size=cadence_window_size,
        min_cadence_samples=min_cadence_samples,
        gap_factor=gap_factor,
        min_jitter_allowance_seconds=min_jitter_allowance_seconds,
        max_cadence_variability=max_cadence_variability,
    )
    _validate_timestamps(observed_timestamps)
    if len(observed_timestamps) < 2:
        return ()

    deltas = tuple(
        (end_at - start_at).total_seconds()
        for start_at, end_at in zip(observed_timestamps, observed_timestamps[1:])
    )
    assessments: list[TemporalIntervalAssessment] = []

    for index, delta_seconds in enumerate(deltas):
        start_at = observed_timestamps[index]
        end_at = observed_timestamps[index + 1]
        if delta_seconds <= 0:
            assessments.append(
                _indeterminate_assessment(
                    start_at=start_at,
                    end_at=end_at,
                    delta_seconds=delta_seconds,
                )
            )
            continue

        left_estimate = _estimate_cadence(
            deltas[max(0, index - cadence_window_size):index],
            min_cadence_samples=min_cadence_samples,
            gap_factor=gap_factor,
            min_jitter_allowance_seconds=min_jitter_allowance_seconds,
            max_cadence_variability=max_cadence_variability,
        )
        right_estimate = _estimate_cadence(
            deltas[index + 1:index + 1 + cadence_window_size],
            min_cadence_samples=min_cadence_samples,
            gap_factor=gap_factor,
            min_jitter_allowance_seconds=min_jitter_allowance_seconds,
            max_cadence_variability=max_cadence_variability,
        )
        assessments.append(
            _assess_interval(
                start_at=start_at,
                end_at=end_at,
                delta_seconds=delta_seconds,
                left_estimate=left_estimate,
                right_estimate=right_estimate,
            )
        )

    return tuple(assessments)


def _estimate_cadence(
    deltas: Sequence[float],
    *,
    min_cadence_samples: int,
    gap_factor: float,
    min_jitter_allowance_seconds: float,
    max_cadence_variability: float,
) -> _CadenceEstimate | None:
    valid_deltas = tuple(delta for delta in deltas if delta > 0)
    if len(valid_deltas) < min_cadence_samples:
        return None

    expected_interval_seconds = float(median(valid_deltas))
    median_absolute_deviation = float(
        median(abs(delta - expected_interval_seconds) for delta in valid_deltas)
    )
    variability = median_absolute_deviation / expected_interval_seconds
    if variability > max_cadence_variability:
        return None

    return _CadenceEstimate(
        expected_interval_seconds=expected_interval_seconds,
        continuity_threshold_seconds=max(
            expected_interval_seconds * gap_factor,
            expected_interval_seconds + min_jitter_allowance_seconds,
        ),
    )


def _assess_interval(
    *,
    start_at: datetime,
    end_at: datetime,
    delta_seconds: float,
    left_estimate: _CadenceEstimate | None,
    right_estimate: _CadenceEstimate | None,
) -> TemporalIntervalAssessment:
    left_supports_continuity = (
        left_estimate is not None
        and delta_seconds <= left_estimate.continuity_threshold_seconds
    )
    right_supports_continuity = (
        right_estimate is not None
        and delta_seconds <= right_estimate.continuity_threshold_seconds
    )

    if left_supports_continuity or right_supports_continuity:
        status = ContinuityStatus.CONTINUOUS
    elif left_estimate is not None and right_estimate is not None:
        status = ContinuityStatus.GAP
    else:
        status = ContinuityStatus.INDETERMINATE

    return TemporalIntervalAssessment(
        start_at=start_at,
        end_at=end_at,
        delta_seconds=delta_seconds,
        status=status,
        cadence_source=_resolve_cadence_source(
            left_estimate=left_estimate,
            right_estimate=right_estimate,
            left_supports_continuity=left_supports_continuity,
            right_supports_continuity=right_supports_continuity,
        ),
        left_expected_interval_seconds=(
            left_estimate.expected_interval_seconds if left_estimate else None
        ),
        right_expected_interval_seconds=(
            right_estimate.expected_interval_seconds if right_estimate else None
        ),
        left_continuity_threshold_seconds=(
            left_estimate.continuity_threshold_seconds if left_estimate else None
        ),
        right_continuity_threshold_seconds=(
            right_estimate.continuity_threshold_seconds if right_estimate else None
        ),
    )


def _resolve_cadence_source(
    *,
    left_estimate: _CadenceEstimate | None,
    right_estimate: _CadenceEstimate | None,
    left_supports_continuity: bool,
    right_supports_continuity: bool,
) -> CadenceSource:
    if left_supports_continuity and right_supports_continuity:
        return CadenceSource.BOTH
    if left_supports_continuity:
        return CadenceSource.LEFT
    if right_supports_continuity:
        return CadenceSource.RIGHT
    if left_estimate is not None and right_estimate is not None:
        return CadenceSource.BOTH
    if left_estimate is not None:
        return CadenceSource.LEFT
    if right_estimate is not None:
        return CadenceSource.RIGHT
    return CadenceSource.NONE


def _indeterminate_assessment(
    *,
    start_at: datetime,
    end_at: datetime,
    delta_seconds: float,
) -> TemporalIntervalAssessment:
    return TemporalIntervalAssessment(
        start_at=start_at,
        end_at=end_at,
        delta_seconds=delta_seconds,
        status=ContinuityStatus.INDETERMINATE,
        cadence_source=CadenceSource.NONE,
        left_expected_interval_seconds=None,
        right_expected_interval_seconds=None,
        left_continuity_threshold_seconds=None,
        right_continuity_threshold_seconds=None,
    )


def _validate_timestamps(observed_timestamps: Sequence[datetime]) -> None:
    previous_timestamp: datetime | None = None
    for timestamp in observed_timestamps:
        if not isinstance(timestamp, datetime):
            raise TemporalContinuityInputError("All observations must be datetimes.")
        if timestamp.tzinfo is not None:
            raise TemporalContinuityInputError(
                "Timestamps must use Manea's UTC-naive datetime convention."
            )
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise TemporalContinuityInputError(
                "Timestamps must be in non-decreasing chronological order."
            )
        previous_timestamp = timestamp


def _validate_configuration(
    *,
    cadence_window_size: int,
    min_cadence_samples: int,
    gap_factor: float,
    min_jitter_allowance_seconds: float,
    max_cadence_variability: float,
) -> None:
    for name, value in (
        ("cadence_window_size", cadence_window_size),
        ("min_cadence_samples", min_cadence_samples),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise TemporalContinuityInputError(f"{name} must be a positive integer.")
    if min_cadence_samples > cadence_window_size:
        raise TemporalContinuityInputError(
            "min_cadence_samples must not exceed cadence_window_size."
        )

    for name, value, allow_zero in (
        ("gap_factor", gap_factor, False),
        ("min_jitter_allowance_seconds", min_jitter_allowance_seconds, True),
        ("max_cadence_variability", max_cadence_variability, True),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TemporalContinuityInputError(f"{name} must be a finite number.")
        if not isfinite(value) or value < 0 or (not allow_zero and value == 0):
            raise TemporalContinuityInputError(f"{name} has an invalid value.")
