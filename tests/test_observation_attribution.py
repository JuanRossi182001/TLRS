import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import fsum

from src.application.analytics.observation_attribution import (
    ContributionSide,
    ObservationAttributionInputError,
    TemporalObservationRef,
    attribute_observed_time_to_observations,
)
from src.application.analytics.observed_time import calculate_observed_time
from src.application.analytics.temporal_continuity import (
    CadenceSource,
    ContinuityStatus,
    TemporalIntervalAssessment,
    analyze_temporal_continuity,
)


START = datetime(2026, 1, 1, 10)
CONTINUOUS = ContinuityStatus.CONTINUOUS
GAP = ContinuityStatus.GAP
INDETERMINATE = ContinuityStatus.INDETERMINATE


def observations_from_deltas(*deltas: float) -> tuple[TemporalObservationRef, ...]:
    timestamps = [START]
    for delta in deltas:
        timestamps.append(timestamps[-1] + timedelta(seconds=delta))
    return tuple(
        TemporalObservationRef(index, timestamp)
        for index, timestamp in enumerate(timestamps, start=1)
    )


def assessments_for(observations, statuses):
    return tuple(
        TemporalIntervalAssessment(
            start_at=left.observed_at,
            end_at=right.observed_at,
            delta_seconds=(right.observed_at - left.observed_at).total_seconds(),
            status=status,
            cadence_source=CadenceSource.NONE,
            left_expected_interval_seconds=None,
            right_expected_interval_seconds=None,
            left_continuity_threshold_seconds=None,
            right_continuity_threshold_seconds=None,
        )
        for left, right, status in zip(observations, observations[1:], statuses)
    )


class ObservationAttributionTests(unittest.TestCase):
    def test_three_stable_observations_preserve_four_separate_ranges(self):
        observations = observations_from_deltas(60, 60)
        assessments = assessments_for(observations, (CONTINUOUS, CONTINUOUS))
        result = attribute_observed_time_to_observations(observations, assessments)

        self.assertEqual(
            [
                (c.observation_id, c.interval_index, c.side,
                 (c.contribution_start - START).total_seconds(),
                 (c.contribution_end - START).total_seconds(), c.observed_seconds)
                for c in result.contributions
            ],
            [
                (1, 0, ContributionSide.LEFT, 0, 30, 30),
                (2, 0, ContributionSide.RIGHT, 30, 60, 30),
                (2, 1, ContributionSide.LEFT, 60, 90, 30),
                (3, 1, ContributionSide.RIGHT, 90, 120, 30),
            ],
        )
        self.assertEqual(result.metadata.observation_count, 3)
        self.assertEqual(result.metadata.assessment_count, 2)
        self.assertEqual(result.metadata.continuous_interval_count, 2)
        self.assertEqual(result.metadata.contribution_count, 4)
        self.assertEqual(result.metadata.contributing_observation_count, 3)
        self.assertEqual(result.metadata.attributed_observed_seconds, 120)
        self.assertEqual(
            result, attribute_observed_time_to_observations(list(observations), list(assessments))
        )

    def test_different_intervals(self):
        observations = observations_from_deltas(60, 120)
        result = attribute_observed_time_to_observations(
            observations, assessments_for(observations, (CONTINUOUS, CONTINUOUS))
        )
        self.assertEqual([c.observed_seconds for c in result.contributions], [30, 30, 60, 60])
        self.assertEqual(result.metadata.attributed_observed_seconds, 180)

    def test_gap_and_indeterminate_leave_holes_and_original_interval_indexes(self):
        for status in (GAP, INDETERMINATE):
            with self.subTest(status=status):
                observations = observations_from_deltas(60, 3600, 60)
                assessments = assessments_for(observations, (CONTINUOUS, status, CONTINUOUS))
                result = attribute_observed_time_to_observations(observations, assessments)
                self.assertEqual([c.interval_index for c in result.contributions], [0, 0, 2, 2])
                self.assertEqual(result.metadata.attributed_observed_seconds, 120)
                self.assertEqual(result.contributions[1].contribution_end, observations[1].observed_at)
                self.assertEqual(result.contributions[2].contribution_start, observations[2].observed_at)

    def test_only_unknown_intervals_have_no_contributing_observations(self):
        observations = observations_from_deltas(60, 600)
        result = attribute_observed_time_to_observations(
            observations, assessments_for(observations, (GAP, INDETERMINATE))
        )
        self.assertEqual(result.contributions, ())
        self.assertEqual(result.metadata.contributing_observation_count, 0)
        self.assertEqual(result.metadata.continuous_interval_count, 0)
        self.assertEqual(result.metadata.attributed_observed_seconds, 0)

    def test_empty_and_single_observation(self):
        for observations in ((), observations_from_deltas()):
            with self.subTest(observations=observations):
                result = attribute_observed_time_to_observations(observations, ())
                self.assertEqual(result.contributions, ())
                self.assertEqual(result.metadata.observation_count, len(observations))
                self.assertEqual(result.metadata.assessment_count, 0)
                self.assertEqual(result.metadata.contribution_count, 0)
                self.assertEqual(result.metadata.attributed_observed_seconds, 0)

    def test_two_observations_produce_two_contributions(self):
        observations = observations_from_deltas(60)
        result = attribute_observed_time_to_observations(
            observations, assessments_for(observations, (CONTINUOUS,))
        )
        self.assertEqual([c.observed_seconds for c in result.contributions], [30, 30])

    def test_repeated_timestamps_with_distinct_ids_are_valid(self):
        observations = observations_from_deltas(0, 60)
        result = attribute_observed_time_to_observations(
            observations, assessments_for(observations, (INDETERMINATE, CONTINUOUS))
        )
        self.assertEqual([c.observation_id for c in result.contributions], [2, 3])
        self.assertEqual(result.metadata.attributed_observed_seconds, 60)

    def test_odd_microseconds_share_a_single_rounded_midpoint(self):
        observations = observations_from_deltas(1.000001)
        result = attribute_observed_time_to_observations(
            observations, assessments_for(observations, (CONTINUOUS,))
        )
        left, right = result.contributions
        self.assertEqual(left.contribution_end, START + timedelta(microseconds=500000))
        self.assertEqual(left.contribution_end, right.contribution_start)
        self.assertEqual(right.contribution_end - right.contribution_start, timedelta(microseconds=500001))
        self.assertEqual(
            sum((c.contribution_end - c.contribution_start for c in result.contributions), timedelta()),
            timedelta(seconds=1, microseconds=1),
        )

    def test_one_microsecond_omits_empty_left_half(self):
        observations = observations_from_deltas(0.000001)
        result = attribute_observed_time_to_observations(
            observations, assessments_for(observations, (CONTINUOUS,))
        )
        self.assertEqual(len(result.contributions), 1)
        contribution = result.contributions[0]
        self.assertEqual(contribution.side, ContributionSide.RIGHT)
        self.assertEqual(contribution.observation_id, 2)
        self.assertEqual(contribution.contribution_start, START)
        self.assertEqual(contribution.observed_seconds, 0.000001)
        self.assertEqual(result.metadata.contributing_observation_count, 1)

    def test_invariants_over_mixed_intervals_and_microsecond_rounding(self):
        deltas = [60, 3600, 1.000001, 0, 0.000001] + [n / 1_000_000 for n in range(2, 102)]
        statuses = [CONTINUOUS, GAP, CONTINUOUS, INDETERMINATE, CONTINUOUS] + [CONTINUOUS] * 100
        observations = observations_from_deltas(*deltas)
        assessments = assessments_for(observations, statuses)
        result = attribute_observed_time_to_observations(observations, assessments)
        total_duration = timedelta()
        for index, assessment in enumerate(assessments):
            parts = [c for c in result.contributions if c.interval_index == index]
            if assessment.status != CONTINUOUS:
                self.assertEqual(parts, [])
                continue
            duration = assessment.end_at - assessment.start_at
            total_duration += duration
            self.assertEqual(len(parts), 1 if duration == timedelta(microseconds=1) else 2)
            self.assertEqual(parts[0].contribution_start, assessment.start_at)
            self.assertEqual(parts[-1].contribution_end, assessment.end_at)
            self.assertEqual(
                sum((c.contribution_end - c.contribution_start for c in parts), timedelta()), duration
            )
            self.assertAlmostEqual(fsum(c.observed_seconds for c in parts), assessment.delta_seconds, places=12)
            for part in parts:
                self.assertGreater(part.contribution_end, part.contribution_start)
                self.assertGreaterEqual(part.contribution_start, assessment.start_at)
                self.assertLessEqual(part.contribution_end, assessment.end_at)
                self.assertEqual(part.observed_seconds, (part.contribution_end - part.contribution_start).total_seconds())
            if len(parts) == 2:
                self.assertEqual(parts[0].contribution_end, parts[1].contribution_start)
        self.assertEqual(
            sum((c.contribution_end - c.contribution_start for c in result.contributions), timedelta()),
            total_duration,
        )
        self.assertEqual(result.metadata.attributed_observed_seconds, total_duration.total_seconds())
        self.assertAlmostEqual(fsum(c.observed_seconds for c in result.contributions), total_duration.total_seconds(), places=12)
        self.assertAlmostEqual(
            calculate_observed_time(assessments).metadata.observed_seconds,
            result.metadata.attributed_observed_seconds, places=12,
        )

    def test_continuity_observed_time_attribution_pipeline(self):
        scenarios = (
            ([60] * 10, 600, None),
            ([60] * 4 + [3600] + [60] * 4, 480, GAP),
            # The detector leaves indexes 1 and 6 indeterminate in this context;
            # attribution must preserve that decision, not count all raw deltas.
            ([5] * 4 + [600] * 5, 2415, CONTINUOUS),
        )
        for deltas, expected, transition_status in scenarios:
            with self.subTest(deltas=deltas):
                observations = observations_from_deltas(*deltas)
                assessments = analyze_temporal_continuity(tuple(o.observed_at for o in observations))
                observed = calculate_observed_time(assessments)
                attributed = attribute_observed_time_to_observations(observations, assessments)
                self.assertEqual(observed.metadata.observed_seconds, expected)
                self.assertEqual(attributed.metadata.attributed_observed_seconds, observed.metadata.observed_seconds)
                self.assertEqual(sum(c.observed_seconds for c in attributed.contributions), expected)
                if transition_status is not None:
                    self.assertEqual(assessments[4].status, transition_status)
                    transition_parts = [c.observed_seconds for c in attributed.contributions if c.interval_index == 4]
                    self.assertEqual(transition_parts, [] if transition_status == GAP else [300, 300])

    def test_incorrect_assessment_counts_are_rejected(self):
        observations = observations_from_deltas(60, 60)
        assessments = assessments_for(observations, (CONTINUOUS, CONTINUOUS))
        for obs, items in ((observations, assessments[:1]), (observations[:1], assessments), ((), assessments)):
            with self.subTest(observations=obs), self.assertRaises(ObservationAttributionInputError):
                attribute_observed_time_to_observations(obs, items)

    def test_invalid_observations_are_rejected(self):
        for invalid_id in (0, -1, True, 1.5, "1", None):
            with self.subTest(id=invalid_id), self.assertRaises(ObservationAttributionInputError):
                attribute_observed_time_to_observations((TemporalObservationRef(invalid_id, START),), ())
        for invalid_time in (START.replace(tzinfo=UTC), "2026-01-01", None):
            with self.subTest(time=invalid_time), self.assertRaises(ObservationAttributionInputError):
                attribute_observed_time_to_observations((TemporalObservationRef(1, invalid_time),), ())
        with self.assertRaises(ObservationAttributionInputError):
            attribute_observed_time_to_observations((object(),), ())

    def test_duplicate_ids_and_out_of_order_observations_are_rejected(self):
        observations = observations_from_deltas(60)
        assessments = assessments_for(observations, (CONTINUOUS,))
        for invalid in (
            (observations[0], replace(observations[1], observation_id=1)),
            tuple(reversed(observations)),
        ):
            with self.subTest(observations=invalid), self.assertRaises(ObservationAttributionInputError):
                attribute_observed_time_to_observations(invalid, assessments)

    def test_invalid_assessments_are_rejected_including_unknown_intervals(self):
        observations = observations_from_deltas(60)
        original = assessments_for(observations, (CONTINUOUS,))[0]
        invalid_changes = [
            {"start_at": START + timedelta(seconds=1)},
            {"end_at": START + timedelta(seconds=59)},
            {"start_at": START.replace(tzinfo=UTC)},
            {"end_at": None},
            {"status": "continuous"},
            {"status": "unsupported"},
        ] + [{"delta_seconds": value} for value in (-1, 59, 60.000001, float("nan"), float("inf"), True, "60", None)]
        for status in (CONTINUOUS, GAP, INDETERMINATE):
            for changes in invalid_changes:
                with self.subTest(status=status, changes=changes), self.assertRaises(ObservationAttributionInputError):
                    attribute_observed_time_to_observations(
                        observations, (replace(replace(original, status=status), **changes),)
                    )
        with self.assertRaises(ObservationAttributionInputError):
            attribute_observed_time_to_observations(observations, (object(),))

    def test_continuous_zero_duration_is_rejected(self):
        observations = observations_from_deltas(0)
        with self.assertRaisesRegex(ObservationAttributionInputError, "positive duration"):
            attribute_observed_time_to_observations(
                observations, assessments_for(observations, (CONTINUOUS,))
            )


if __name__ == "__main__":
    unittest.main()
