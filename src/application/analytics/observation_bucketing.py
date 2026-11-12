"""Intersect one temporal sequence's attributed time with UTC-aligned buckets."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Sequence

from src.application.analytics.observation_attribution import (
    ContributionSide,
    ObservationTimeContribution,
)
from src.application.analytics.temporal_bucketing import floor_bucket_start


class ObservationBucketAttributionInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObservationBucketContribution:
    observation_id: int
    interval_index: int
    bucket_start: datetime
    bucket_end: datetime
    contribution_start: datetime
    contribution_end: datetime
    observed_seconds: float
    side: ContributionSide


@dataclass(frozen=True, slots=True)
class ObservationBucketAttributionMetadata:
    window_start: datetime
    window_end: datetime
    bucket_seconds: int
    input_contribution_count: int
    output_contribution_count: int
    input_observed_seconds: float
    in_window_observed_seconds: float
    outside_window_observed_seconds: float
    bucketed_observed_seconds: float
    bucket_count: int


@dataclass(frozen=True, slots=True)
class ObservationBucketAttributionResult:
    contributions: tuple[ObservationBucketContribution, ...]
    metadata: ObservationBucketAttributionMetadata


def bucket_observation_contributions(
    *,
    contributions: Sequence[ObservationTimeContribution],
    window_start: datetime,
    window_end: datetime,
    bucket_seconds: int,
) -> ObservationBucketAttributionResult:
    """Clip and partition positive, ordered, non-overlapping contributions.

    Input belongs to one temporal sequence, not several devices. Adjacent ranges
    and repeated observation IDs are valid; ranges remain separate. All ranges
    are half-open. Timedelta totals conserve microseconds; float fields are only
    projections of those durations. Continuity and attribution are not inferred.
    """
    _validate_timestamp(window_start)
    _validate_timestamp(window_end)
    if window_end <= window_start:
        raise ObservationBucketAttributionInputError(
            "window_end must be later than window_start."
        )
    if isinstance(bucket_seconds, bool) or not isinstance(bucket_seconds, int) or bucket_seconds <= 0:
        raise ObservationBucketAttributionInputError("bucket_seconds must be a positive integer.")
    _validate_contributions(contributions)

    output: list[ObservationBucketContribution] = []
    input_duration = timedelta()
    in_window_duration = timedelta()
    bucketed_duration = timedelta()
    bucket_starts: set[datetime] = set()
    try:
        bucket_duration = timedelta(seconds=bucket_seconds)
        for contribution in contributions:
            input_duration += contribution.contribution_end - contribution.contribution_start
            start = max(contribution.contribution_start, window_start)
            end = min(contribution.contribution_end, window_end)
            if start >= end:
                continue
            in_window_duration += end - start
            while start < end:
                bucket_start = floor_bucket_start(start, bucket_seconds)
                bucket_end = bucket_start + bucket_duration
                segment_end = min(end, bucket_end)
                duration = segment_end - start
                output.append(
                    ObservationBucketContribution(
                        observation_id=contribution.observation_id,
                        interval_index=contribution.interval_index,
                        bucket_start=bucket_start,
                        bucket_end=bucket_end,
                        contribution_start=start,
                        contribution_end=segment_end,
                        observed_seconds=duration.total_seconds(),
                        side=contribution.side,
                    )
                )
                bucket_starts.add(bucket_start)
                bucketed_duration += duration
                start = segment_end
    except OverflowError as exc:
        raise ObservationBucketAttributionInputError(
            "Bucket boundaries must fit datetime's supported range."
        ) from exc

    output.sort(key=lambda item: (
        item.bucket_start,
        item.contribution_start,
        item.interval_index,
        0 if item.side == ContributionSide.LEFT else 1,
        item.observation_id,
    ))
    return ObservationBucketAttributionResult(
        contributions=tuple(output),
        metadata=ObservationBucketAttributionMetadata(
            window_start=window_start,
            window_end=window_end,
            bucket_seconds=bucket_seconds,
            input_contribution_count=len(contributions),
            output_contribution_count=len(output),
            input_observed_seconds=input_duration.total_seconds(),
            in_window_observed_seconds=in_window_duration.total_seconds(),
            outside_window_observed_seconds=(input_duration - in_window_duration).total_seconds(),
            bucketed_observed_seconds=bucketed_duration.total_seconds(),
            bucket_count=len(bucket_starts),
        ),
    )


def _validate_contributions(contributions: Sequence[ObservationTimeContribution]) -> None:
    previous: ObservationTimeContribution | None = None
    for contribution in contributions:
        if not isinstance(contribution, ObservationTimeContribution):
            raise ObservationBucketAttributionInputError(
                "All contributions must be ObservationTimeContribution values."
            )
        for name, value, minimum in (
            ("observation_id", contribution.observation_id, 1),
            ("interval_index", contribution.interval_index, 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ObservationBucketAttributionInputError(f"Invalid {name}.")
        if not isinstance(contribution.side, ContributionSide):
            raise ObservationBucketAttributionInputError("Invalid contribution side.")
        _validate_timestamp(contribution.contribution_start)
        _validate_timestamp(contribution.contribution_end)
        duration = contribution.contribution_end - contribution.contribution_start
        if duration <= timedelta():
            raise ObservationBucketAttributionInputError("Contributions must have positive duration.")
        seconds = contribution.observed_seconds
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or seconds != duration.total_seconds()
            or not isfinite(seconds)
        ):
            raise ObservationBucketAttributionInputError(
                "observed_seconds must be finite and match the contribution duration."
            )
        if previous is not None:
            if contribution.contribution_start < previous.contribution_end:
                raise ObservationBucketAttributionInputError(
                    "Contributions must be ordered and must not overlap."
                )
            if contribution.interval_index < previous.interval_index:
                raise ObservationBucketAttributionInputError("Interval indexes must be non-decreasing.")
            if contribution.interval_index == previous.interval_index and (
                previous.side != ContributionSide.LEFT or contribution.side != ContributionSide.RIGHT
            ):
                raise ObservationBucketAttributionInputError(
                    "An interval's sides must be unique and ordered LEFT before RIGHT."
                )
        previous = contribution


def _validate_timestamp(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise ObservationBucketAttributionInputError(
            "Timestamps must use Manea's UTC-naive datetime convention."
        )
