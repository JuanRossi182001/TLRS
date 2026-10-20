import unittest
from datetime import UTC, datetime, timedelta

from src.application.analytics.observed_time import (
    ObservedSpan,
    calculate_observed_time,
)
from src.application.analytics.temporal_bucketing import (
    UTC_NAIVE_EPOCH,
    TemporalBucketingInputError,
    bucket_observed_time,
)
from src.application.analytics.temporal_continuity import analyze_temporal_continuity


START = datetime(2026, 1, 1, 10, 0, 0)
FIVE_MINUTES = 300


def span(start_at: datetime, end_at: datetime) -> ObservedSpan:
    return ObservedSpan(
        start_at=start_at,
        end_at=end_at,
        observed_seconds=(end_at - start_at).total_seconds(),
    )


def timestamps_from_deltas(*deltas: float) -> tuple[datetime, ...]:
    timestamps = [START]
    for delta in deltas:
        timestamps.append(timestamps[-1] + timedelta(seconds=delta))
    return tuple(timestamps)


class TemporalBucketingTests(unittest.TestCase):
    def test_span_inside_one_bucket(self) -> None:
        result = self._bucket((span(self._at(minutes=1), self._at(minutes=3)),))

        self.assertEqual(len(result.buckets), 1)
        self.assertEqual(result.buckets[0].bucket_start, START)
        self.assertEqual(result.buckets[0].observed_seconds, 120)

    def test_span_crossing_one_boundary_is_split(self) -> None:
        result = self._bucket((span(self._at(minutes=4), self._at(minutes=7)),))

        self.assertEqual(
            [(item.bucket_start, item.observed_seconds) for item in result.buckets],
            [(START, 60), (self._at(minutes=5), 120)],
        )

    def test_span_crossing_multiple_buckets_conserves_time(self) -> None:
        result = self._bucket((span(self._at(minutes=3), self._at(minutes=18)),))

        self.assertEqual(
            [item.observed_seconds for item in result.buckets],
            [120, 300, 300, 180],
        )
        self.assertEqual(result.metadata.in_window_observed_seconds, 900)
        self.assertEqual(result.metadata.bucketed_observed_seconds, 900)

    def test_multiple_spans_accumulate_in_one_bucket(self) -> None:
        result = self._bucket(
            (
                span(START, self._at(minutes=1)),
                span(self._at(minutes=1), self._at(minutes=2)),
                span(self._at(minutes=3), self._at(minutes=4)),
            )
        )

        self.assertEqual(len(result.buckets), 1)
        self.assertEqual(result.buckets[0].observed_seconds, 180)
        self.assertEqual(result.buckets[0].contributing_span_count, 3)

    def test_adjacent_spans_are_accepted_without_double_counting(self) -> None:
        result = self._bucket(
            (
                span(START, self._at(minutes=1)),
                span(self._at(minutes=1), self._at(minutes=2)),
            )
        )

        self.assertEqual(result.metadata.bucketed_observed_seconds, 120)
        self.assertEqual(result.buckets[0].observed_seconds, 120)

    def test_clipping_at_window_start(self) -> None:
        result = self._bucket(
            (span(self._at(minutes=-5), self._at(minutes=5)),),
            window_start=START,
            window_end=self._at(hours=1),
        )

        self.assertEqual(result.metadata.input_observed_seconds, 600)
        self.assertEqual(result.metadata.in_window_observed_seconds, 300)
        self.assertEqual(result.metadata.outside_window_observed_seconds, 300)
        self.assertEqual(result.buckets[0].observed_seconds, 300)

    def test_clipping_at_window_end(self) -> None:
        result = self._bucket(
            (span(self._at(minutes=55), self._at(minutes=65)),),
            window_start=START,
            window_end=self._at(hours=1),
        )

        self.assertEqual(result.metadata.in_window_observed_seconds, 300)
        self.assertEqual(result.metadata.outside_window_observed_seconds, 300)
        self.assertEqual(result.buckets[0].bucket_start, self._at(minutes=55))
        self.assertEqual(result.buckets[0].observed_seconds, 300)

    def test_spans_outside_window_do_not_materialize_buckets(self) -> None:
        result = self._bucket(
            (
                span(self._at(hours=-2), self._at(hours=-1)),
                span(self._at(hours=2), self._at(hours=3)),
            ),
            window_start=START,
            window_end=self._at(hours=1),
        )

        self.assertEqual(result.buckets, ())
        self.assertEqual(result.metadata.in_window_observed_seconds, 0)
        self.assertEqual(result.metadata.outside_window_observed_seconds, 7_200)

    def test_exact_window_boundary_uses_one_bucket(self) -> None:
        result = self._bucket((span(START, self._at(minutes=5)),))

        self.assertEqual(len(result.buckets), 1)
        self.assertEqual(result.buckets[0].bucket_start, START)
        self.assertEqual(result.buckets[0].bucket_end, self._at(minutes=5))
        self.assertEqual(result.buckets[0].observed_seconds, 300)

    def test_microseconds_are_split_without_rounding_loss(self) -> None:
        result = self._bucket(
            (
                span(
                    self._at(minutes=4, seconds=59, microseconds=500_000),
                    self._at(minutes=5, microseconds=500_000),
                ),
            )
        )

        self.assertEqual(
            [item.observed_seconds for item in result.buckets],
            [0.5, 0.5],
        )
        self.assertEqual(result.metadata.bucketed_observed_seconds, 1.0)

    def test_empty_input_returns_empty_result(self) -> None:
        result = self._bucket(())

        self.assertEqual(result.buckets, ())
        self.assertEqual(result.metadata.input_observed_seconds, 0)
        self.assertEqual(result.metadata.in_window_observed_seconds, 0)
        self.assertEqual(result.metadata.bucketed_observed_seconds, 0)

    def test_rejects_overlapping_and_out_of_order_spans(self) -> None:
        overlapping = (
            span(START, self._at(minutes=3)),
            span(self._at(minutes=2), self._at(minutes=4)),
        )
        out_of_order = (
            span(self._at(minutes=5), self._at(minutes=6)),
            span(START, self._at(minutes=1)),
        )

        for spans in (overlapping, out_of_order):
            with self.subTest(spans=spans), self.assertRaisesRegex(
                TemporalBucketingInputError,
                "ordered",
            ):
                self._bucket(spans)

    def test_rejects_invalid_parameters(self) -> None:
        valid_span = span(START, self._at(minutes=1))
        invalid_cases = (
            {"window_start": START, "window_end": START},
            {"window_start": self._at(minutes=5), "window_end": START},
            {"bucket_seconds": 0},
            {"bucket_seconds": -1},
            {
                "window_start": START.replace(tzinfo=UTC),
                "window_end": self._at(minutes=5).replace(tzinfo=UTC),
            },
        )

        for kwargs in invalid_cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(TemporalBucketingInputError):
                self._bucket((valid_span,), **kwargs)

    def test_bucket_invariants_hold(self) -> None:
        result = self._bucket(
            (
                span(self._at(minutes=3), self._at(minutes=18)),
                span(self._at(minutes=20), self._at(minutes=22)),
            ),
            window_start=START,
            window_end=self._at(minutes=25),
        )

        self.assertEqual(
            result.metadata.bucketed_observed_seconds,
            result.metadata.in_window_observed_seconds,
        )
        self.assertTrue(
            all(0 < item.observed_seconds <= FIVE_MINUTES for item in result.buckets)
        )
        self.assertEqual(
            [item.bucket_start for item in result.buckets],
            sorted(item.bucket_start for item in result.buckets),
        )
        self.assertEqual(
            len({item.bucket_start for item in result.buckets}),
            len(result.buckets),
        )
        self.assertTrue(
            all(
                (item.bucket_end - item.bucket_start).total_seconds() == FIVE_MINUTES
                for item in result.buckets
            )
        )
        self.assertTrue(
            all(
                ((item.bucket_start - UTC_NAIVE_EPOCH).total_seconds() % FIVE_MINUTES)
                == 0
                for item in result.buckets
            )
        )
        self.assertLessEqual(
            result.metadata.in_window_observed_seconds,
            result.metadata.input_observed_seconds,
        )

    def test_continuity_pipeline_distributes_stable_series(self) -> None:
        observed_time = calculate_observed_time(
            analyze_temporal_continuity(timestamps_from_deltas(*([60] * 10)))
        )

        result = self._bucket(observed_time.spans, window_end=self._at(minutes=10))

        self.assertEqual(
            [item.observed_seconds for item in result.buckets],
            [300, 300],
        )

    def test_continuity_pipeline_does_not_fill_gap_buckets(self) -> None:
        observed_time = calculate_observed_time(
            analyze_temporal_continuity(
                timestamps_from_deltas(*([60] * 4 + [3_600] + [60] * 4))
            )
        )

        result = self._bucket(
            observed_time.spans,
            window_end=self._at(hours=2),
        )

        self.assertEqual(result.metadata.bucketed_observed_seconds, 480)
        self.assertFalse(
            any(
                self._at(minutes=5) <= item.bucket_start < self._at(hours=1)
                for item in result.buckets
            )
        )

    def test_continuity_pipeline_preserves_legitimate_slow_transition(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([5] * 4 + [600] + [600] * 4))
        )
        observed_time = calculate_observed_time(assessments)

        result = self._bucket(observed_time.spans, window_end=self._at(hours=1))

        transition = assessments[4]
        self.assertEqual(transition.delta_seconds, 600)
        self.assertEqual(
            sum(
                bucket.observed_seconds
                for bucket in result.buckets
                if transition.start_at <= bucket.bucket_start < transition.end_at
            ),
            600,
        )

    def _bucket(self, spans, **overrides):
        return bucket_observed_time(
            spans=spans,
            window_start=overrides.get("window_start", START),
            window_end=overrides.get("window_end", self._at(minutes=30)),
            bucket_seconds=overrides.get("bucket_seconds", FIVE_MINUTES),
        )

    @staticmethod
    def _at(
        *,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        microseconds: int = 0,
    ) -> datetime:
        return START + timedelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            microseconds=microseconds,
        )


if __name__ == "__main__":
    unittest.main()
