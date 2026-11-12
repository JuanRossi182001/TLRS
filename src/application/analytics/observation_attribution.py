"""Nearest-observation temporal attribution, independent of spatial information.

Each continuous interval is partitioned at one midpoint. Its endpoints represent
the resulting time ranges; this does not imply immobility or interpolate a path.
Ranges are half-open and remain separate for assessment-level traceability.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite
from typing import Sequence

from src.application.analytics.temporal_continuity import (
    ContinuityStatus,
    TemporalIntervalAssessment,
)


class ObservationAttributionInputError(ValueError):
    pass


class ContributionSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class TemporalObservationRef:
    observation_id: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ObservationTimeContribution:
    observation_id: int
    interval_index: int
    contribution_start: datetime
    contribution_end: datetime
    observed_seconds: float
    side: ContributionSide


@dataclass(frozen=True, slots=True)
class ObservationAttributionMetadata:
    observation_count: int
    assessment_count: int
    continuous_interval_count: int
    contribution_count: int
    attributed_observed_seconds: float
    contributing_observation_count: int


@dataclass(frozen=True, slots=True)
class ObservationAttributionResult:
    contributions: tuple[ObservationTimeContribution, ...]
    metadata: ObservationAttributionMetadata


def attribute_observed_time_to_observations(
    observations: Sequence[TemporalObservationRef],
    assessments: Sequence[TemporalIntervalAssessment],
) -> ObservationAttributionResult:
    """Partition continuous intervals, ordered by interval index then LEFT/RIGHT.

    IDs must be unique positive integers; repeated timestamps are allowed.
    One midpoint is rounded to datetime's microsecond resolution using native
    timedelta division (round-half-to-even). Empty halves are omitted: a 1 us
    interval therefore produces only a RIGHT contribution. Temporal ranges and
    their timedelta sum conserve time exactly; float seconds are projections.
    """
    _validate_inputs(observations, assessments)
    contributions: list[ObservationTimeContribution] = []
    contributing_ids: set[int] = set()
    attributed_duration = timedelta()
    continuous_interval_count = 0

    for index, assessment in enumerate(assessments):
        if assessment.status != ContinuityStatus.CONTINUOUS:
            continue

        continuous_interval_count += 1
        duration = assessment.end_at - assessment.start_at
        midpoint = assessment.start_at + duration / 2
        for observation, start, end, side in (
            (observations[index], assessment.start_at, midpoint, ContributionSide.LEFT),
            (observations[index + 1], midpoint, assessment.end_at, ContributionSide.RIGHT),
        ):
            if start == end:
                continue
            contribution_duration = end - start
            contributions.append(
                ObservationTimeContribution(
                    observation_id=observation.observation_id,
                    interval_index=index,
                    contribution_start=start,
                    contribution_end=end,
                    observed_seconds=contribution_duration.total_seconds(),
                    side=side,
                )
            )
            contributing_ids.add(observation.observation_id)
        attributed_duration += duration

    return ObservationAttributionResult(
        contributions=tuple(contributions),
        metadata=ObservationAttributionMetadata(
            observation_count=len(observations),
            assessment_count=len(assessments),
            continuous_interval_count=continuous_interval_count,
            contribution_count=len(contributions),
            attributed_observed_seconds=attributed_duration.total_seconds(),
            contributing_observation_count=len(contributing_ids),
        ),
    )


def _validate_inputs(
    observations: Sequence[TemporalObservationRef],
    assessments: Sequence[TemporalIntervalAssessment],
) -> None:
    if len(assessments) != max(len(observations) - 1, 0):
        raise ObservationAttributionInputError(
            "Assessment count must equal max(observation count - 1, 0)."
        )

    seen_ids: set[int] = set()
    previous_timestamp: datetime | None = None
    for observation in observations:
        if not isinstance(observation, TemporalObservationRef):
            raise ObservationAttributionInputError(
                "All observations must be TemporalObservationRef values."
            )
        observation_id = observation.observation_id
        if (
            isinstance(observation_id, bool)
            or not isinstance(observation_id, int)
            or observation_id <= 0
        ):
            raise ObservationAttributionInputError(
                "observation_id must be a positive integer."
            )
        if observation_id in seen_ids:
            raise ObservationAttributionInputError("Duplicate observation IDs are not allowed.")
        seen_ids.add(observation_id)
        _validate_timestamp(observation.observed_at)
        if previous_timestamp is not None and observation.observed_at < previous_timestamp:
            raise ObservationAttributionInputError(
                "Observations must be in non-decreasing chronological order."
            )
        previous_timestamp = observation.observed_at

    for index, assessment in enumerate(assessments):
        if not isinstance(assessment, TemporalIntervalAssessment):
            raise ObservationAttributionInputError(
                "All assessments must be TemporalIntervalAssessment values."
            )
        _validate_timestamp(assessment.start_at)
        _validate_timestamp(assessment.end_at)
        if (
            assessment.start_at != observations[index].observed_at
            or assessment.end_at != observations[index + 1].observed_at
        ):
            raise ObservationAttributionInputError(
                "Assessment timestamps must match the corresponding observations."
            )
        if not isinstance(assessment.status, ContinuityStatus):
            raise ObservationAttributionInputError("Unsupported continuity status.")
        delta = assessment.delta_seconds
        if (
            isinstance(delta, bool)
            or not isinstance(delta, (int, float))
            or delta < 0
            or delta != (assessment.end_at - assessment.start_at).total_seconds()
            or not isfinite(delta)
        ):
            raise ObservationAttributionInputError(
                "Assessment delta_seconds must be finite, non-negative and match its timestamps."
            )
        if assessment.status == ContinuityStatus.CONTINUOUS and delta == 0:
            raise ObservationAttributionInputError(
                "CONTINUOUS intervals must have positive duration."
            )


def _validate_timestamp(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise ObservationAttributionInputError(
            "Timestamps must use Manea's UTC-naive datetime convention."
        )
