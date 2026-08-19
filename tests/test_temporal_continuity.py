import unittest
from datetime import UTC, datetime, timedelta

from src.application.analytics.temporal_continuity import (
    CadenceSource,
    ContinuityStatus,
    TemporalContinuityInputError,
    analyze_temporal_continuity,
)


START = datetime(2026, 1, 1, 0, 0, 0)


def timestamps_from_deltas(*deltas: float) -> tuple[datetime, ...]:
    timestamps = [START]
    for delta in deltas:
        timestamps.append(timestamps[-1] + timedelta(seconds=delta))
    return tuple(timestamps)


class TemporalContinuityTests(unittest.TestCase):
    def test_stable_60_second_cadence_is_continuous(self) -> None:
        assessments = analyze_temporal_continuity(timestamps_from_deltas(*([60] * 10)))

        self.assertTrue(
            all(item.status == ContinuityStatus.CONTINUOUS for item in assessments)
        )

    def test_stable_fast_cadence_tolerates_jitter(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([5, 6, 4, 5, 6, 4, 5, 5, 4, 6]))
        )

        self.assertTrue(
            all(item.status == ContinuityStatus.CONTINUOUS for item in assessments)
        )

    def test_stable_600_second_cadence_is_continuous(self) -> None:
        assessments = analyze_temporal_continuity(timestamps_from_deltas(*([600] * 10)))

        self.assertTrue(
            all(item.status == ContinuityStatus.CONTINUOUS for item in assessments)
        )

    def test_clear_gap_between_stable_contexts_is_a_gap(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([60] * 4 + [3_600] + [60] * 4))
        )

        assessment = assessments[4]
        self.assertEqual(assessment.status, ContinuityStatus.GAP)
        self.assertEqual(assessment.cadence_source, CadenceSource.BOTH)
        self.assertEqual(assessment.left_expected_interval_seconds, 60)
        self.assertEqual(assessment.right_expected_interval_seconds, 60)
        self.assertEqual(assessment.left_continuity_threshold_seconds, 180)

    def test_legitimate_change_from_5_to_600_seconds_is_continuous(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([5] * 4 + [600] + [600] * 4))
        )

        assessment = assessments[4]
        self.assertEqual(assessment.status, ContinuityStatus.CONTINUOUS)
        self.assertEqual(assessment.cadence_source, CadenceSource.RIGHT)
        self.assertEqual(assessment.left_expected_interval_seconds, 5)
        self.assertEqual(assessment.right_expected_interval_seconds, 600)
        self.assertEqual(assessment.right_continuity_threshold_seconds, 1_800)

    def test_legitimate_change_from_600_to_5_seconds_is_continuous(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([600] * 4 + [5] + [5] * 4))
        )

        assessment = assessments[4]
        self.assertEqual(assessment.status, ContinuityStatus.CONTINUOUS)
        self.assertEqual(assessment.cadence_source, CadenceSource.BOTH)
        self.assertEqual(assessment.left_expected_interval_seconds, 600)
        self.assertEqual(assessment.right_expected_interval_seconds, 5)

    def test_legitimate_change_from_15_to_30_seconds_is_continuous(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([15] * 4 + [30] + [30] * 4))
        )

        self.assertEqual(assessments[4].status, ContinuityStatus.CONTINUOUS)

    def test_default_threshold_tolerates_up_to_two_missing_60_second_reports(self) -> None:
        one_missing = analyze_temporal_continuity(
            timestamps_from_deltas(*([60] * 4 + [120] + [60] * 4))
        )
        two_missing = analyze_temporal_continuity(
            timestamps_from_deltas(*([60] * 4 + [180] + [60] * 4))
        )
        three_missing = analyze_temporal_continuity(
            timestamps_from_deltas(*([60] * 4 + [240] + [60] * 4))
        )

        self.assertEqual(one_missing[4].status, ContinuityStatus.CONTINUOUS)
        self.assertEqual(two_missing[4].status, ContinuityStatus.CONTINUOUS)
        self.assertEqual(three_missing[4].status, ContinuityStatus.GAP)

    def test_gap_before_new_slow_cadence_remains_a_gap(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([60] * 4 + [3_600] + [600] * 4))
        )

        self.assertEqual(assessments[4].status, ContinuityStatus.GAP)
        self.assertEqual(assessments[4].left_continuity_threshold_seconds, 180)
        self.assertEqual(assessments[4].right_continuity_threshold_seconds, 1_800)

    def test_two_timestamps_are_indeterminate(self) -> None:
        assessments = analyze_temporal_continuity(timestamps_from_deltas(600))

        self.assertEqual(len(assessments), 1)
        self.assertEqual(assessments[0].status, ContinuityStatus.INDETERMINATE)
        self.assertEqual(assessments[0].cadence_source, CadenceSource.NONE)

    def test_left_edge_can_use_only_right_context(self) -> None:
        assessments = analyze_temporal_continuity(timestamps_from_deltas(*([600] * 5)))

        self.assertEqual(assessments[0].status, ContinuityStatus.CONTINUOUS)
        self.assertEqual(assessments[0].cadence_source, CadenceSource.RIGHT)

    def test_single_incompatible_context_is_indeterminate_not_gap(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([3_600] + [60] * 4))
        )

        self.assertEqual(assessments[0].status, ContinuityStatus.INDETERMINATE)
        self.assertEqual(assessments[0].cadence_source, CadenceSource.RIGHT)

    def test_right_edge_can_use_only_left_context(self) -> None:
        assessments = analyze_temporal_continuity(timestamps_from_deltas(*([600] * 5)))

        self.assertEqual(assessments[-1].status, ContinuityStatus.CONTINUOUS)
        self.assertEqual(assessments[-1].cadence_source, CadenceSource.LEFT)

    def test_irregular_context_does_not_invent_cadence(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(
                5,
                600,
                30,
                120,
                15,
                1_000,
                5,
                600,
                30,
                120,
                15,
            )
        )

        assessment = assessments[5]
        self.assertEqual(assessment.status, ContinuityStatus.INDETERMINATE)
        self.assertEqual(assessment.cadence_source, CadenceSource.NONE)
        self.assertIsNone(assessment.left_expected_interval_seconds)
        self.assertIsNone(assessment.right_expected_interval_seconds)

    def test_median_and_mad_resist_single_context_outlier(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(
                60,
                60,
                61,
                900,
                59,
                60,
                60,
                60,
                60,
                60,
                60,
            )
        )

        assessment = assessments[6]
        self.assertEqual(assessment.status, ContinuityStatus.CONTINUOUS)
        self.assertEqual(assessment.left_expected_interval_seconds, 60.5)

    def test_out_of_order_timestamps_raise_controlled_error(self) -> None:
        timestamps = (START, START + timedelta(seconds=60), START + timedelta(seconds=30))

        with self.assertRaisesRegex(TemporalContinuityInputError, "non-decreasing"):
            analyze_temporal_continuity(timestamps)

    def test_duplicate_timestamps_are_indeterminate_and_not_cadence_samples(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(60, 60, 0, 60, 60, 60, 60, 60, 60)
        )

        self.assertEqual(assessments[2].delta_seconds, 0)
        self.assertEqual(assessments[2].status, ContinuityStatus.INDETERMINATE)
        self.assertEqual(assessments[4].left_expected_interval_seconds, 60)

    def test_empty_and_single_timestamp_sequences_have_no_intervals(self) -> None:
        self.assertEqual(analyze_temporal_continuity(()), ())
        self.assertEqual(analyze_temporal_continuity((START,)), ())

    def test_aware_timestamps_are_rejected(self) -> None:
        aware_timestamp = START.replace(tzinfo=UTC)

        with self.assertRaisesRegex(TemporalContinuityInputError, "UTC-naive"):
            analyze_temporal_continuity((aware_timestamp, aware_timestamp))

    def test_invalid_configuration_is_rejected(self) -> None:
        invalid_configurations = (
            {"cadence_window_size": 0},
            {"min_cadence_samples": 0},
            {"cadence_window_size": 2, "min_cadence_samples": 3},
            {"gap_factor": 0},
            {"min_jitter_allowance_seconds": -1},
            {"max_cadence_variability": -0.1},
        )
        timestamps = timestamps_from_deltas(60, 60, 60, 60)

        for kwargs in invalid_configurations:
            with self.subTest(kwargs=kwargs), self.assertRaises(TemporalContinuityInputError):
                analyze_temporal_continuity(timestamps, **kwargs)

    def test_only_positive_deltas_contribute_to_cadence_estimates(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(60, 60, 0, 60, 60, 60, 60, 60)
        )

        self.assertEqual(assessments[4].left_expected_interval_seconds, 60)


if __name__ == "__main__":
    unittest.main()
