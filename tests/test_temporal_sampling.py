import unittest
from math import ceil

from src.application.analytics.temporal_sampling import (
    ALLOWED_BUCKET_SECONDS,
    BucketResolutionLimitError,
    DEFAULT_MAX_POINTS,
    DEFAULT_TARGET_POINTS,
    MAX_BUCKET_SECONDS,
    MIN_BUCKET_SECONDS,
    calculate_bucket_resolution,
)


MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR


class TemporalSamplingTests(unittest.TestCase):
    def test_representative_scenarios(self) -> None:
        scenarios = (
            ("1 device / 1 hour", HOUR, 1, 60, 60),
            ("1 device / 24 hours", DAY, 1, 60, 1_440),
            ("1 device / 7 days", 7 * DAY, 1, 60, 10_080),
            ("1 device / 30 days", 30 * DAY, 1, 300, 8_640),
            ("10 devices / 24 hours", DAY, 10, 60, 14_400),
            ("50 devices / 24 hours", DAY, 50, 300, 14_400),
            ("50 devices / 7 days", 7 * DAY, 50, 2_700, 11_200),
            ("50 devices / 30 days", 30 * DAY, 50, 10_800, 12_000),
            ("100 devices / 30 days", 30 * DAY, 100, 21_600, 12_000),
        )

        for name, window_seconds, device_count, expected_bucket, expected_points in scenarios:
            with self.subTest(name=name):
                result = calculate_bucket_resolution(
                    window_seconds=window_seconds,
                    device_count=device_count,
                )
                self.assertEqual(result.bucket_seconds, expected_bucket)
                self.assertEqual(result.estimated_points, expected_points)

    def test_selects_next_bucket_when_smaller_exceeds_target(self) -> None:
        result = calculate_bucket_resolution(
            window_seconds=114,
            device_count=10,
            target_points=19,
            max_points=20,
        )

        self.assertEqual(result.required_bucket_seconds, 60)
        self.assertEqual(result.bucket_seconds, 120)
        self.assertEqual(result.estimated_points, 10)
        self.assertTrue(result.target_met)

    def test_selects_smallest_bucket_when_multiple_buckets_meet_target(self) -> None:
        result = calculate_bucket_resolution(
            window_seconds=DAY,
            device_count=1,
        )

        self.assertEqual(result.bucket_seconds, MIN_BUCKET_SECONDS)
        self.assertEqual(result.estimated_points, 1_440)

    def test_returns_max_safe_resolution_when_target_cannot_be_met(self) -> None:
        result = calculate_bucket_resolution(
            window_seconds=20_000 * DAY,
            device_count=1,
        )

        self.assertEqual(result.bucket_seconds, MAX_BUCKET_SECONDS)
        self.assertEqual(result.estimated_points, 20_000)
        self.assertFalse(result.target_met)
        self.assertLessEqual(result.estimated_points, DEFAULT_MAX_POINTS)

    def test_raises_when_max_bucket_cannot_meet_absolute_limit(self) -> None:
        with self.assertRaises(BucketResolutionLimitError) as context:
            calculate_bucket_resolution(
                window_seconds=30 * DAY,
                device_count=100_000,
            )

        self.assertGreater(context.exception.estimated_points, DEFAULT_MAX_POINTS)
        self.assertEqual(context.exception.max_bucket_seconds, MAX_BUCKET_SECONDS)

    def test_zero_devices_returns_minimum_bucket_and_no_points(self) -> None:
        result = calculate_bucket_resolution(
            window_seconds=DAY,
            device_count=0,
        )

        self.assertEqual(result.bucket_seconds, MIN_BUCKET_SECONDS)
        self.assertEqual(result.estimated_points, 0)
        self.assertTrue(result.target_met)

    def test_rejects_invalid_inputs(self) -> None:
        invalid_cases = (
            {"window_seconds": 0, "device_count": 1},
            {"window_seconds": -1, "device_count": 1},
            {"window_seconds": float("inf"), "device_count": 1},
            {"window_seconds": DAY, "device_count": -1},
            {"window_seconds": DAY, "device_count": 1, "target_points": 0},
            {"window_seconds": DAY, "device_count": 1, "max_points": 0},
            {
                "window_seconds": DAY,
                "device_count": 1,
                "target_points": 100,
                "max_points": 99,
            },
            {
                "window_seconds": DAY,
                "device_count": 1,
                "min_bucket_seconds": 3_600,
                "max_bucket_seconds": 60,
            },
        )

        for kwargs in invalid_cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                calculate_bucket_resolution(**kwargs)

    def test_rejects_limits_without_an_allowed_resolution(self) -> None:
        with self.assertRaisesRegex(ValueError, "No allowed bucket"):
            calculate_bucket_resolution(
                window_seconds=DAY,
                device_count=1,
                min_bucket_seconds=61,
                max_bucket_seconds=119,
            )

    def test_more_devices_never_choose_a_smaller_bucket(self) -> None:
        buckets = [
            calculate_bucket_resolution(
                window_seconds=DAY,
                device_count=device_count,
            ).bucket_seconds
            for device_count in (0, 1, 10, 50, 100)
        ]

        self.assertEqual(buckets, sorted(buckets))

    def test_larger_windows_never_choose_a_smaller_bucket(self) -> None:
        buckets = [
            calculate_bucket_resolution(
                window_seconds=window_seconds,
                device_count=50,
            ).bucket_seconds
            for window_seconds in (HOUR, DAY, 7 * DAY, 30 * DAY)
        ]

        self.assertEqual(buckets, sorted(buckets))

    def test_resolution_invariants_hold_for_supported_scenarios(self) -> None:
        for window_seconds in (HOUR, DAY, 7 * DAY, 30 * DAY):
            for device_count in (0, 1, 10, 50, 100):
                with self.subTest(
                    window_seconds=window_seconds,
                    device_count=device_count,
                ):
                    result = calculate_bucket_resolution(
                        window_seconds=window_seconds,
                        device_count=device_count,
                    )
                    self.assertIn(result.bucket_seconds, ALLOWED_BUCKET_SECONDS)
                    self.assertGreaterEqual(result.bucket_seconds, MIN_BUCKET_SECONDS)
                    self.assertLessEqual(result.bucket_seconds, MAX_BUCKET_SECONDS)
                    self.assertLessEqual(result.estimated_points, DEFAULT_MAX_POINTS)
                    if result.target_met:
                        self.assertLessEqual(
                            result.estimated_points,
                            DEFAULT_TARGET_POINTS,
                        )

    def test_selected_bucket_is_the_smallest_that_meets_its_constraint(self) -> None:
        scenarios = (
            (DAY, 50),
            (30 * DAY, 1),
            (20_000 * DAY, 1),
        )

        for window_seconds, device_count in scenarios:
            with self.subTest(
                window_seconds=window_seconds,
                device_count=device_count,
            ):
                result = calculate_bucket_resolution(
                    window_seconds=window_seconds,
                    device_count=device_count,
                )
                limit = (
                    DEFAULT_TARGET_POINTS if result.target_met else DEFAULT_MAX_POINTS
                )
                for bucket_seconds in ALLOWED_BUCKET_SECONDS:
                    if bucket_seconds >= result.bucket_seconds:
                        break
                    estimated_points = ceil(window_seconds / bucket_seconds) * device_count
                    self.assertGreater(estimated_points, limit)

    def test_custom_limits_constrain_the_selected_bucket(self) -> None:
        result = calculate_bucket_resolution(
            window_seconds=DAY,
            device_count=10,
            target_points=15_000,
            max_points=25_000,
            min_bucket_seconds=120,
            max_bucket_seconds=600,
        )

        self.assertEqual(result.bucket_seconds, 120)
        self.assertEqual(result.estimated_points, 7_200)


if __name__ == "__main__":
    unittest.main()
