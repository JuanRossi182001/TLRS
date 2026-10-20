import unittest
from datetime import datetime, timedelta

from src.application.analytics.observed_time import (
    ObservedTimeInputError,
    calculate_observed_time,
)
from src.application.analytics.temporal_continuity import (
    CadenceSource,
    ContinuityStatus,
    TemporalIntervalAssessment,
    analyze_temporal_continuity,
)


START = datetime(2026, 1, 1, 10, 0, 0)


def assessment(
    *,
    start_at: datetime,
    delta_seconds: float,
    status: ContinuityStatus,
    end_at: datetime | None = None,
) -> TemporalIntervalAssessment:
    return TemporalIntervalAssessment(
        start_at=start_at,
        end_at=end_at or start_at + timedelta(seconds=delta_seconds),
        delta_seconds=delta_seconds,
        status=status,
        cadence_source=CadenceSource.NONE,
        left_expected_interval_seconds=None,
        right_expected_interval_seconds=None,
        left_continuity_threshold_seconds=None,
        right_continuity_threshold_seconds=None,
    )


def timestamps_from_deltas(*deltas: float) -> tuple[datetime, ...]:
    timestamps = [START]
    for delta in deltas:
        timestamps.append(timestamps[-1] + timedelta(seconds=delta))
    return tuple(timestamps)


class ObservedTimeTests(unittest.TestCase):
    def test_all_continuous_intervals_are_observed(self) -> None:
        assessments = tuple(
            assessment(
                start_at=START + timedelta(seconds=index * 60),
                delta_seconds=60,
                status=ContinuityStatus.CONTINUOUS,
            )
            for index in range(4)
        )

        result = calculate_observed_time(assessments)

        self.assertEqual(result.metadata.observed_seconds, 240)
        self.assertEqual(result.metadata.unknown_seconds, 0)
        self.assertEqual(len(result.spans), 4)

    def test_all_gap_intervals_are_unknown(self) -> None:
        assessments = (
            assessment(start_at=START, delta_seconds=600, status=ContinuityStatus.GAP),
            assessment(
                start_at=START + timedelta(seconds=600),
                delta_seconds=3_600,
                status=ContinuityStatus.GAP,
            ),
        )

        result = calculate_observed_time(assessments)

        self.assertEqual(result.metadata.observed_seconds, 0)
        self.assertEqual(result.metadata.gap_seconds, 4_200)
        self.assertEqual(result.metadata.unknown_seconds, 4_200)
        self.assertEqual(result.spans, ())

    def test_all_indeterminate_intervals_are_unknown(self) -> None:
        assessments = (
            assessment(
                start_at=START,
                delta_seconds=600,
                status=ContinuityStatus.INDETERMINATE,
            ),
            assessment(
                start_at=START + timedelta(seconds=600),
                delta_seconds=60,
                status=ContinuityStatus.INDETERMINATE,
            ),
        )

        result = calculate_observed_time(assessments)

        self.assertEqual(result.metadata.observed_seconds, 0)
        self.assertEqual(result.metadata.indeterminate_seconds, 660)
        self.assertEqual(result.metadata.unknown_seconds, 660)
        self.assertEqual(result.spans, ())

    def test_mixed_assessments_preserve_spans_and_totals(self) -> None:
        assessments = self._mixed_assessments()

        result = calculate_observed_time(assessments)

        self.assertEqual(result.metadata.observed_seconds, 360)
        self.assertEqual(result.metadata.gap_seconds, 3_600)
        self.assertEqual(result.metadata.indeterminate_seconds, 600)
        self.assertEqual(result.metadata.unknown_seconds, 4_200)
        self.assertEqual(result.metadata.assessed_seconds, 4_560)
        self.assertEqual(result.metadata.assessment_count, 6)
        self.assertEqual(result.metadata.continuous_interval_count, 4)
        self.assertEqual(result.metadata.gap_interval_count, 1)
        self.assertEqual(result.metadata.indeterminate_interval_count, 1)
        self.assertEqual(len(result.spans), 4)
        self.assertEqual(result.spans[2].observed_seconds, 180)

    def test_continuous_180_second_interval_contributes_all_its_time(self) -> None:
        result = calculate_observed_time(
            (
                assessment(
                    start_at=START,
                    delta_seconds=180,
                    status=ContinuityStatus.CONTINUOUS,
                ),
            )
        )

        self.assertEqual(result.metadata.observed_seconds, 180)
        self.assertEqual(result.spans[0].observed_seconds, 180)

    def test_long_indeterminate_interval_never_becomes_observed(self) -> None:
        result = calculate_observed_time(
            (
                assessment(
                    start_at=START,
                    delta_seconds=7_200,
                    status=ContinuityStatus.INDETERMINATE,
                ),
            )
        )

        self.assertEqual(result.metadata.observed_seconds, 0)
        self.assertEqual(result.metadata.indeterminate_seconds, 7_200)

    def test_zero_duration_duplicate_assessment_is_counted_but_not_summed(self) -> None:
        result = calculate_observed_time(
            (
                assessment(
                    start_at=START,
                    delta_seconds=0,
                    status=ContinuityStatus.INDETERMINATE,
                ),
            )
        )

        self.assertEqual(result.metadata.assessment_count, 1)
        self.assertEqual(result.metadata.indeterminate_interval_count, 1)
        self.assertEqual(result.metadata.indeterminate_seconds, 0)
        self.assertEqual(result.spans, ())

    def test_empty_input_returns_empty_result(self) -> None:
        result = calculate_observed_time(())

        self.assertEqual(result.spans, ())
        self.assertEqual(result.metadata.observed_seconds, 0)
        self.assertEqual(result.metadata.assessed_seconds, 0)
        self.assertEqual(result.metadata.assessment_count, 0)

    def test_single_continuous_assessment_produces_one_span(self) -> None:
        item = assessment(
            start_at=START,
            delta_seconds=60,
            status=ContinuityStatus.CONTINUOUS,
        )

        result = calculate_observed_time((item,))

        self.assertEqual(len(result.spans), 1)
        self.assertEqual(result.spans[0].start_at, START)
        self.assertEqual(result.spans[0].end_at, START + timedelta(seconds=60))

    def test_consecutive_continuous_intervals_are_not_merged(self) -> None:
        first = assessment(
            start_at=START,
            delta_seconds=60,
            status=ContinuityStatus.CONTINUOUS,
        )
        second = assessment(
            start_at=START + timedelta(seconds=60),
            delta_seconds=60,
            status=ContinuityStatus.CONTINUOUS,
        )

        result = calculate_observed_time((first, second))

        self.assertEqual(len(result.spans), 2)
        self.assertEqual(result.spans[0].end_at, result.spans[1].start_at)

    def test_rejects_negative_duration(self) -> None:
        with self.assertRaisesRegex(ObservedTimeInputError, "end_at"):
            calculate_observed_time(
                (
                    assessment(
                        start_at=START,
                        delta_seconds=-60,
                        status=ContinuityStatus.GAP,
                    ),
                )
            )

    def test_rejects_timestamp_delta_mismatch(self) -> None:
        with self.assertRaisesRegex(ObservedTimeInputError, "must match"):
            calculate_observed_time(
                (
                    assessment(
                        start_at=START,
                        delta_seconds=12,
                        end_at=START + timedelta(minutes=10),
                        status=ContinuityStatus.CONTINUOUS,
                    ),
                )
            )

    def test_metadata_and_spans_invariants(self) -> None:
        result = calculate_observed_time(self._mixed_assessments())
        metadata = result.metadata

        self.assertEqual(
            metadata.observed_seconds
            + metadata.gap_seconds
            + metadata.indeterminate_seconds,
            metadata.assessed_seconds,
        )
        self.assertEqual(len(result.spans), metadata.continuous_interval_count)
        self.assertEqual(
            sum(span.observed_seconds for span in result.spans),
            metadata.observed_seconds,
        )
        self.assertTrue(all(span.end_at > span.start_at for span in result.spans))

    def test_stable_cadence_integrates_to_observed_time(self) -> None:
        assessments = analyze_temporal_continuity(timestamps_from_deltas(*([60] * 10)))

        result = calculate_observed_time(assessments)

        self.assertEqual(result.metadata.observed_seconds, 600)
        self.assertEqual(result.metadata.unknown_seconds, 0)

    def test_clear_gap_from_continuity_detector_is_not_observed(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([60] * 4 + [3_600] + [60] * 4))
        )

        result = calculate_observed_time(assessments)

        self.assertEqual(result.metadata.observed_seconds, 480)
        self.assertEqual(result.metadata.gap_seconds, 3_600)

    def test_legitimate_cadence_change_counts_the_full_transition(self) -> None:
        assessments = analyze_temporal_continuity(
            timestamps_from_deltas(*([5] * 4 + [600] + [600] * 4))
        )

        result = calculate_observed_time(assessments)

        transition = assessments[4]
        self.assertEqual(transition.status, ContinuityStatus.CONTINUOUS)
        self.assertIn(
            (transition.start_at, transition.end_at, 600),
            {
                (span.start_at, span.end_at, span.observed_seconds)
                for span in result.spans
            },
        )
        self.assertEqual(
            result.metadata.observed_seconds,
            sum(
                item.delta_seconds
                for item in assessments
                if item.status == ContinuityStatus.CONTINUOUS
            ),
        )

    def _mixed_assessments(self) -> tuple[TemporalIntervalAssessment, ...]:
        statuses_and_deltas = (
            (ContinuityStatus.CONTINUOUS, 60),
            (ContinuityStatus.CONTINUOUS, 60),
            (ContinuityStatus.CONTINUOUS, 180),
            (ContinuityStatus.GAP, 3_600),
            (ContinuityStatus.INDETERMINATE, 600),
            (ContinuityStatus.CONTINUOUS, 60),
        )
        start_at = START
        assessments = []
        for status, delta_seconds in statuses_and_deltas:
            assessments.append(
                assessment(
                    start_at=start_at,
                    delta_seconds=delta_seconds,
                    status=status,
                )
            )
            start_at += timedelta(seconds=delta_seconds)
        return tuple(assessments)


if __name__ == "__main__":
    unittest.main()
