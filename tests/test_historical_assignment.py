import unittest
from datetime import datetime, timedelta

from src.application.analytics.historical_assignment import (
    AssignmentRef, AssignmentHistoryInputError, resolve_assignment_windows, temporal_coverage_ratio,
)


START = datetime(2026, 1, 1)


def a(assignment_id, asset_id, device_id, start, end=None):
    return AssignmentRef(assignment_id, asset_id, device_id, START + timedelta(seconds=start),
                         None if end is None else START + timedelta(seconds=end))


class AssignmentHistoryTests(unittest.TestCase):
    def test_reassignment_and_exclusive_boundary(self):
        history = (a(1, 183, 15, 0, 60), a(2, 417, 15, 60, 120))
        result = resolve_assignment_windows(history, window_start=START + timedelta(seconds=30),
                                            window_end=START + timedelta(seconds=90))
        self.assertEqual([(w.assignment.asset_id, (w.end_at - w.start_at).total_seconds())
                          for w in result.windows], [(183, 30), (417, 30)])
        self.assertEqual(result.eligible_assignment_seconds, 60)

    def test_open_partial_unassigned_and_multiple_devices(self):
        history = (a(1, 1, 10, -50, 0), a(2, 1, 11, 20, 70), a(3, 2, 10, 70, None))
        result = resolve_assignment_windows(history, window_start=START, window_end=START + timedelta(seconds=100))
        self.assertEqual([w.assignment.assignment_id for w in result.windows], [2, 3])
        self.assertEqual(result.eligible_assignment_seconds, 80)
        self.assertEqual(temporal_coverage_ratio(40, 80), 0.5)
        self.assertIsNone(temporal_coverage_ratio(0, 0))

    def test_no_invented_history_and_exact_empty_assignment(self):
        result = resolve_assignment_windows((a(1, 1, 2, 50), a(2, 3, 4, 0, 0)),
                                            window_start=START, window_end=START + timedelta(seconds=100))
        self.assertEqual(result.eligible_assignment_seconds, 50)
        self.assertEqual(len(result.windows), 1)

    def test_reject_overlap_for_either_device_or_asset_even_outside_window(self):
        for second in (a(2, 2, 1, 50, 80), a(2, 1, 2, 50, 80), a(2, 2, 1, 99)):
            with self.subTest(second=second), self.assertRaises(AssignmentHistoryInputError):
                resolve_assignment_windows((a(1, 1, 1, 0, 100), second),
                                           window_start=START, window_end=START + timedelta(seconds=20))
        with self.assertRaises(AssignmentHistoryInputError):
            temporal_coverage_ratio(11, 10)
        with self.assertRaises(AssignmentHistoryInputError):
            temporal_coverage_ratio(float("nan"), 10)


if __name__ == "__main__":
    unittest.main()
