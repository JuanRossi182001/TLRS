from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isclose
from typing import Sequence

from src.application.analytics.observed_time import ObservedSpan


UTC_NAIVE_EPOCH = datetime(1970, 1, 1)


class TemporalBucketingInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TemporalBucket:
    bucket_start: datetime
    bucket_end: datetime
    observed_seconds: float
    contributing_span_count: int


@dataclass(frozen=True, slots=True)
class TemporalBucketingMetadata:
    window_start: datetime
    window_end: datetime
    bucket_seconds: int
    input_observed_seconds: float
    in_window_observed_seconds: float
    outside_window_observed_seconds: float
    bucketed_observed_seconds: float
    input_span_count: int
    contributing_span_count: int
    bucket_count: int


@dataclass(frozen=True, slots=True)
class TemporalBucketingResult:
    buckets: tuple[TemporalBucket, ...]
    metadata: TemporalBucketingMetadata


def bucket_observed_time(
    *,
    spans: Sequence[ObservedSpan],
    window_start: datetime,
    window_end: datetime,
    bucket_seconds: int,
) -> TemporalBucketingResult:
    """Clip observed spans and distribute their time across UTC-aligned buckets."""
    _validate_window(window_start, window_end)
    _validate_bucket_seconds(bucket_seconds)
    _validate_spans(spans)

    bucket_duration = timedelta(seconds=bucket_seconds)
    bucket_totals: dict[datetime, list[float | int]] = {}
    input_observed_seconds = sum(span.observed_seconds for span in spans)
    in_window_observed_seconds = 0.0
    contributing_span_count = 0

    for span in spans:
        clipped_start = max(span.start_at, window_start)
        clipped_end = min(span.end_at, window_end)
        if clipped_start >= clipped_end:
            continue

        contributing_span_count += 1
        clipped_seconds = (clipped_end - clipped_start).total_seconds()
        in_window_observed_seconds += clipped_seconds
        current_start = clipped_start

        while current_start < clipped_end:
            bucket_start = _floor_bucket_start(current_start, bucket_seconds)
            bucket_end = bucket_start + bucket_duration
            segment_end = min(bucket_end, clipped_end)
            segment_seconds = (segment_end - current_start).total_seconds()

            total = bucket_totals.setdefault(bucket_start, [0.0, 0])
            total[0] += segment_seconds
            total[1] += 1
            current_start = segment_end

    buckets = tuple(
        _build_bucket(
            bucket_start=bucket_start,
            observed_seconds=float(total[0]),
            contributing_span_count=int(total[1]),
            bucket_duration=bucket_duration,
            bucket_seconds=bucket_seconds,
        )
        for bucket_start, total in sorted(bucket_totals.items())
    )
    bucketed_observed_seconds = sum(bucket.observed_seconds for bucket in buckets)
    if not isclose(
        bucketed_observed_seconds,
        in_window_observed_seconds,
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        raise TemporalBucketingInputError(
            "Bucketed observed time does not match in-window observed time."
        )

    outside_window_observed_seconds = input_observed_seconds - in_window_observed_seconds
    if isclose(outside_window_observed_seconds, 0.0, abs_tol=1e-6):
        outside_window_observed_seconds = 0.0

    return TemporalBucketingResult(
        buckets=buckets,
        metadata=TemporalBucketingMetadata(
            window_start=window_start,
            window_end=window_end,
            bucket_seconds=bucket_seconds,
            input_observed_seconds=input_observed_seconds,
            in_window_observed_seconds=in_window_observed_seconds,
            outside_window_observed_seconds=outside_window_observed_seconds,
            bucketed_observed_seconds=bucketed_observed_seconds,
            input_span_count=len(spans),
            contributing_span_count=contributing_span_count,
            bucket_count=len(buckets),
        ),
    )


def _floor_bucket_start(timestamp: datetime, bucket_seconds: int) -> datetime:
    offset = timestamp - UTC_NAIVE_EPOCH
    offset_microseconds = (
        (offset.days * 86_400 + offset.seconds) * 1_000_000
        + offset.microseconds
    )
    bucket_microseconds = bucket_seconds * 1_000_000
    return UTC_NAIVE_EPOCH + timedelta(
        microseconds=(offset_microseconds // bucket_microseconds) * bucket_microseconds
    )


def _build_bucket(
    *,
    bucket_start: datetime,
    observed_seconds: float,
    contributing_span_count: int,
    bucket_duration: timedelta,
    bucket_seconds: int,
) -> TemporalBucket:
    if observed_seconds <= 0 or observed_seconds > bucket_seconds + 1e-6:
        raise TemporalBucketingInputError(
            "A temporal bucket has an invalid observed time total."
        )
    return TemporalBucket(
        bucket_start=bucket_start,
        bucket_end=bucket_start + bucket_duration,
        observed_seconds=observed_seconds,
        contributing_span_count=contributing_span_count,
    )


def _validate_window(window_start: datetime, window_end: datetime) -> None:
    _validate_utc_naive_datetime(window_start, "window_start")
    _validate_utc_naive_datetime(window_end, "window_end")
    if window_end <= window_start:
        raise TemporalBucketingInputError("window_end must be later than window_start.")


def _validate_bucket_seconds(bucket_seconds: int) -> None:
    if (
        isinstance(bucket_seconds, bool)
        or not isinstance(bucket_seconds, int)
        or bucket_seconds <= 0
    ):
        raise TemporalBucketingInputError("bucket_seconds must be a positive integer.")


def _validate_spans(spans: Sequence[ObservedSpan]) -> None:
    previous_end: datetime | None = None
    for span in spans:
        if not isinstance(span, ObservedSpan):
            raise TemporalBucketingInputError("All inputs must be ObservedSpan values.")
        _validate_utc_naive_datetime(span.start_at, "span.start_at")
        _validate_utc_naive_datetime(span.end_at, "span.end_at")
        if span.end_at <= span.start_at:
            raise TemporalBucketingInputError("Observed spans must have positive duration.")
        if span.observed_seconds <= 0:
            raise TemporalBucketingInputError(
                "Observed spans must have positive observed_seconds."
            )

        duration_seconds = (span.end_at - span.start_at).total_seconds()
        if not isclose(
            span.observed_seconds,
            duration_seconds,
            rel_tol=1e-9,
            abs_tol=1e-6,
        ):
            raise TemporalBucketingInputError(
                "ObservedSpan observed_seconds must match its timestamp interval."
            )
        if previous_end is not None and span.start_at < previous_end:
            raise TemporalBucketingInputError(
                "Observed spans must be ordered and must not overlap."
            )
        previous_end = span.end_at


def _validate_utc_naive_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise TemporalBucketingInputError(
            f"{field_name} must use Manea's UTC-naive datetime convention."
        )
