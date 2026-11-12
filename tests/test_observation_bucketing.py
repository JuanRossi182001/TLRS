import unittest
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import fsum

from src.application.analytics.observation_attribution import (
    ContributionSide,
    ObservationTimeContribution,
    TemporalObservationRef,
    attribute_observed_time_to_observations,
)
from src.application.analytics.observation_bucketing import (
    ObservationBucketAttributionInputError,
    ObservationBucketAttributionResult,
    bucket_observation_contributions,
)
from src.application.analytics.observed_time import calculate_observed_time
from src.application.analytics.temporal_bucketing import (
    UTC_NAIVE_EPOCH,
    bucket_observed_time,
)
from src.application.analytics.temporal_continuity import (
    ContinuityStatus,
    analyze_temporal_continuity,
)


START = datetime(2026, 1, 1, 10)
LEFT = ContributionSide.LEFT
RIGHT = ContributionSide.RIGHT


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def contribution(
    start: datetime,
    end: datetime,
    observation_id: int = 1,
    interval_index: int = 0,
    side: ContributionSide = LEFT,
) -> ObservationTimeContribution:
    return ObservationTimeContribution(
        observation_id=observation_id,
        interval_index=interval_index,
        contribution_start=start,
        contribution_end=end,
        observed_seconds=(end - start).total_seconds(),
        side=side,
    )


class ObservationBucketingTests(unittest.TestCase):
    def _bucket(self, contributions, **overrides) -> ObservationBucketAttributionResult:
        return bucket_observation_contributions(
            contributions=contributions,
            window_start=overrides.get("window_start", START),
            window_end=overrides.get("window_end", at(3600)),
            bucket_seconds=overrides.get("bucket_seconds", 300),
        )

    def test_inside_one_bucket(self) -> None:
        result = self._bucket((contribution(at(60), at(180)),))
        self.assertEqual(len(result.contributions), 1)
        item = result.contributions[0]
        self.assertEqual((item.bucket_start, item.bucket_end), (START, at(300)))
        self.assertEqual((item.contribution_start, item.contribution_end), (at(60), at(180)))
        self.assertEqual(item.observed_seconds, 120)

    def test_crosses_one_boundary(self) -> None:
        result = self._bucket((contribution(at(240), at(420)),))
        self.assertEqual(
            [(c.bucket_start, c.observed_seconds) for c in result.contributions],
            [(START, 60), (at(300), 120)],
        )

    def test_crosses_multiple_buckets(self) -> None:
        result = self._bucket((contribution(at(180), at(1080)),))
        self.assertEqual([c.observed_seconds for c in result.contributions], [120, 300, 300, 180])
        self.assertEqual(result.metadata.bucket_count, 4)
        self.assertEqual(result.metadata.bucketed_observed_seconds, 900)

    def test_main_example_conserves_observation_and_bucket_totals(self) -> None:
        inputs = (
            contribution(at(240), at(330)),
            contribution(at(330), at(420), observation_id=2, side=RIGHT),
        )
        result = self._bucket(inputs)
        self.assertEqual(
            [(c.bucket_start, c.observation_id, c.observed_seconds) for c in result.contributions],
            [(START, 1, 60), (at(300), 1, 30), (at(300), 2, 90)],
        )
        by_observation = defaultdict(float)
        by_bucket = defaultdict(float)
        for item in result.contributions:
            by_observation[item.observation_id] += item.observed_seconds
            by_bucket[item.bucket_start] += item.observed_seconds
        self.assertEqual(dict(by_observation), {1: 90, 2: 90})
        self.assertEqual(dict(by_bucket), {START: 60, at(300): 120})
        self.assertEqual(result.metadata.input_contribution_count, 2)
        self.assertEqual(result.metadata.output_contribution_count, 3)
        self.assertEqual(result.metadata.bucket_count, 2)
        self.assertEqual(result.metadata.input_observed_seconds, 180)
        self.assertEqual(result.metadata.in_window_observed_seconds, 180)
        self.assertEqual(result.metadata.bucketed_observed_seconds, 180)
        self.assertEqual(result.metadata.outside_window_observed_seconds, 0)

    def test_clipping_start(self) -> None:
        result = self._bucket((contribution(at(-120), at(180)),))
        self.assertEqual(result.metadata.input_observed_seconds, 300)
        self.assertEqual(result.metadata.in_window_observed_seconds, 180)
        self.assertEqual(result.metadata.outside_window_observed_seconds, 120)
        self.assertEqual(result.contributions[0].contribution_start, START)

    def test_clipping_end(self) -> None:
        result = self._bucket((contribution(at(3540), at(3720)),))
        self.assertEqual(result.metadata.in_window_observed_seconds, 60)
        self.assertEqual(result.metadata.outside_window_observed_seconds, 120)
        self.assertEqual(result.contributions[-1].contribution_end, at(3600))

    def test_clipping_both_ends_preserves_full_bucket_boundaries(self) -> None:
        result = self._bucket(
            (contribution(START, at(600)),), window_start=at(90), window_end=at(390)
        )
        self.assertEqual([c.observed_seconds for c in result.contributions], [210, 90])
        self.assertEqual(result.metadata.outside_window_observed_seconds, 300)
        self.assertEqual(result.contributions[0].bucket_start, START)
        self.assertEqual(result.contributions[-1].bucket_end, at(600))

    def test_outside_and_touching_window_do_not_produce_segments(self) -> None:
        result = self._bucket((
            contribution(at(-60), START),
            contribution(at(3600), at(3660), interval_index=1),
        ))
        self.assertEqual(result.contributions, ())
        self.assertEqual(result.metadata.bucket_count, 0)
        self.assertEqual(result.metadata.in_window_observed_seconds, 0)
        self.assertEqual(result.metadata.outside_window_observed_seconds, 120)

    def test_exact_boundary_is_half_open(self) -> None:
        result = self._bucket((
            contribution(START, at(300)),
            contribution(at(300), at(600), observation_id=2, side=RIGHT),
        ))
        self.assertEqual(
            [(c.bucket_start, c.observed_seconds) for c in result.contributions],
            [(START, 300), (at(300), 300)],
        )

    def test_microseconds_split_without_loss(self) -> None:
        for start, end, expected in (
            (at(299.5), at(300.5), [0.5, 0.5]),
            (at(299.999999), at(300.000002), [0.000001, 0.000002]),
            (at(300), at(300.000001), [0.000001]),
        ):
            with self.subTest(start=start):
                result = self._bucket((contribution(start, end, side=RIGHT),))
                self.assertEqual([c.observed_seconds for c in result.contributions], expected)
                self.assertEqual(
                    sum((c.contribution_end - c.contribution_start for c in result.contributions), timedelta()),
                    end - start,
                )
                self.assertAlmostEqual(fsum(expected), result.metadata.bucketed_observed_seconds, places=12)

    def test_same_observation_is_not_merged_and_order_is_reproducible(self) -> None:
        inputs = (
            contribution(at(30), at(60), observation_id=2, interval_index=0, side=RIGHT),
            contribution(at(60), at(90), observation_id=2, interval_index=1, side=LEFT),
        )
        result = self._bucket(inputs)
        self.assertEqual(len(result.contributions), 2)
        self.assertEqual(sum(c.observed_seconds for c in result.contributions), 60)
        self.assertEqual([(c.interval_index, c.side) for c in result.contributions], [(0, RIGHT), (1, LEFT)])
        self.assertEqual(result, self._bucket(list(inputs)))
        self.assertEqual(
            list(result.contributions),
            sorted(result.contributions, key=lambda c: (
                c.bucket_start, c.contribution_start, c.interval_index,
                0 if c.side == LEFT else 1, c.observation_id,
            )),
        )

    def test_empty_input(self) -> None:
        result = self._bucket(())
        self.assertEqual(result.contributions, ())
        for field in (
            "input_contribution_count", "output_contribution_count", "input_observed_seconds",
            "in_window_observed_seconds", "outside_window_observed_seconds",
            "bucketed_observed_seconds", "bucket_count",
        ):
            self.assertEqual(getattr(result.metadata, field), 0)

    def test_invalid_order_or_overlap_is_rejected_even_outside_window(self) -> None:
        first = contribution(START, at(60))
        for inputs in (
            (contribution(at(90), at(120)), first),
            (first, contribution(at(30), at(90), observation_id=2, side=RIGHT)),
            (first, first),
        ):
            with self.subTest(inputs=inputs), self.assertRaises(ObservationBucketAttributionInputError):
                self._bucket(inputs, window_start=at(1200), window_end=at(1800))

    def test_invalid_traceability_is_rejected(self) -> None:
        first = contribution(START, at(60), interval_index=1)
        for second in (
            contribution(at(60), at(90), interval_index=0),
            contribution(at(60), at(90), interval_index=1),
        ):
            with self.subTest(second=second), self.assertRaises(ObservationBucketAttributionInputError):
                self._bucket((first, second))
        with self.assertRaises(ObservationBucketAttributionInputError):
            self._bucket((replace(first, side=RIGHT), contribution(at(60), at(90), interval_index=1)))

    def test_invalid_contribution_fields_are_rejected(self) -> None:
        original = contribution(START, at(60))
        invalid = [
            {"observation_id": value} for value in (0, -1, True, 1.5, "1")
        ] + [
            {"interval_index": value} for value in (-1, False, 1.5, "0")
        ] + [
            {"observed_seconds": value}
            for value in (0, -1, 59, 60.000001, float("nan"), float("inf"), True, "60", None)
        ] + [
            {"contribution_start": START.replace(tzinfo=UTC)},
            {"contribution_end": at(60).replace(tzinfo=UTC)},
            {"contribution_start": "invalid"},
            {"contribution_end": None},
            {"contribution_end": START},
            {"contribution_end": at(-1)},
            {"side": "left"},
            {"side": None},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ObservationBucketAttributionInputError):
                self._bucket((replace(original, **changes),))
        with self.assertRaises(ObservationBucketAttributionInputError):
            self._bucket((object(),))

    def test_invalid_parameters_are_rejected_including_empty_input(self) -> None:
        invalid = [
            {"window_end": START},
            {"window_end": at(-1)},
            {"window_start": START.replace(tzinfo=UTC)},
            {"window_end": at(3600).replace(tzinfo=UTC)},
            {"window_start": None},
        ] + [{"bucket_seconds": value} for value in (0, -1, True, 1.5, "300", None, 10**100)]
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ObservationBucketAttributionInputError):
                self._bucket((), **overrides)

    def test_unrepresentable_bucket_boundary_is_controlled_error(self) -> None:
        start = datetime(9999, 12, 31, 23, 59, 58)
        end = start + timedelta(seconds=1)
        with self.assertRaises(ObservationBucketAttributionInputError):
            self._bucket((contribution(start, end),), window_start=start, window_end=end)

    def test_alignment_before_epoch_and_nonstandard_bucket_size(self) -> None:
        start = UTC_NAIVE_EPOCH - timedelta(seconds=2)
        end = UTC_NAIVE_EPOCH + timedelta(seconds=2)
        result = self._bucket(
            (contribution(start, end),), window_start=start, window_end=end, bucket_seconds=7
        )
        self.assertEqual([c.observed_seconds for c in result.contributions], [2, 2])
        self.assertEqual(
            [c.bucket_start for c in result.contributions],
            [UTC_NAIVE_EPOCH - timedelta(seconds=7), UTC_NAIVE_EPOCH],
        )

    def test_pipeline_matches_1a5_and_preserves_all_invariants(self) -> None:
        scenarios = (
            ("stable", [60] * 10, 600),
            ("gap", [60] * 4 + [3600] + [60] * 4, 480),
            ("cadence_change", [5] * 4 + [600] * 5, 2415),
            ("microseconds", [1.000001] * 10, 10.00001),
        )
        for name, deltas, full_expected in scenarios:
            timestamps = [at(240)]
            for delta in deltas:
                timestamps.append(timestamps[-1] + timedelta(seconds=delta))
            observations = tuple(TemporalObservationRef(i, t) for i, t in enumerate(timestamps, 1))
            assessments = analyze_temporal_continuity(timestamps)
            observed = calculate_observed_time(assessments)
            attributed = attribute_observed_time_to_observations(observations, assessments)
            for window_start, window_end in (
                (START, timestamps[-1] + timedelta(seconds=1)),
                (timestamps[0] + timedelta(microseconds=1), timestamps[-1] - timedelta(microseconds=1)),
            ):
                with self.subTest(scenario=name, window=(window_start, window_end)):
                    result = self._bucket(
                        attributed.contributions, window_start=window_start, window_end=window_end
                    )
                    reference = bucket_observed_time(
                        spans=observed.spans, window_start=window_start,
                        window_end=window_end, bucket_seconds=300,
                    )
                    by_bucket = defaultdict(list)
                    by_observation = defaultdict(timedelta)
                    for item in result.contributions:
                        by_bucket[item.bucket_start].append(item.observed_seconds)
                        duration = item.contribution_end - item.contribution_start
                        by_observation[item.observation_id] += duration
                        self.assertGreater(duration, timedelta())
                        self.assertLessEqual(item.bucket_start, item.contribution_start)
                        self.assertLessEqual(item.contribution_end, item.bucket_end)
                        self.assertGreaterEqual(item.contribution_start, window_start)
                        self.assertLessEqual(item.contribution_end, window_end)
                        self.assertEqual((item.bucket_start - UTC_NAIVE_EPOCH) % timedelta(seconds=300), timedelta())
                        self.assertEqual(item.bucket_end - item.bucket_start, timedelta(seconds=300))
                        source = next(c for c in attributed.contributions if (
                            c.interval_index, c.side
                        ) == (item.interval_index, item.side))
                        self.assertEqual(item.observation_id, source.observation_id)
                        self.assertGreaterEqual(item.contribution_start, source.contribution_start)
                        self.assertLessEqual(item.contribution_end, source.contribution_end)
                        self.assertEqual(assessments[item.interval_index].status, ContinuityStatus.CONTINUOUS)
                    expected_by_observation = defaultdict(timedelta)
                    for source in attributed.contributions:
                        start = max(source.contribution_start, window_start)
                        end = min(source.contribution_end, window_end)
                        if start < end:
                            expected_by_observation[source.observation_id] += end - start
                    self.assertEqual(dict(by_observation), dict(expected_by_observation))
                    self.assertEqual(set(by_bucket), {b.bucket_start for b in reference.buckets})
                    for bucket in reference.buckets:
                        self.assertAlmostEqual(fsum(by_bucket[bucket.bucket_start]), bucket.observed_seconds, places=9)
                    self.assertEqual(result.metadata.bucketed_observed_seconds, result.metadata.in_window_observed_seconds)
                    self.assertAlmostEqual(result.metadata.bucketed_observed_seconds, reference.metadata.bucketed_observed_seconds, places=9)
                    self.assertEqual(
                        sum(by_observation.values(), timedelta()).total_seconds(),
                        result.metadata.in_window_observed_seconds,
                    )
                    if window_start == START:
                        self.assertAlmostEqual(result.metadata.bucketed_observed_seconds, full_expected, places=9)
                    if name == "cadence_change":
                        self.assertEqual(assessments[4].status, ContinuityStatus.CONTINUOUS)
                        self.assertEqual(sum(c.observed_seconds for c in result.contributions if c.interval_index == 4), 600)
                    if name == "gap":
                        gap = assessments[4]
                        self.assertEqual(gap.status, ContinuityStatus.GAP)
                        self.assertTrue(all(
                            c.contribution_end <= gap.start_at or c.contribution_start >= gap.end_at
                            for c in result.contributions
                        ))


if __name__ == "__main__":
    unittest.main()
