import unittest
from dataclasses import replace
from datetime import datetime, timedelta

from pyproj import Geod

from src.application.analytics.spatial_assessment import (
    SpatialAssessmentConfig, SpatialAssessmentInputError,
    SpatialAssessmentReason, SpatialIntervalStatus, SpatialObservationRef,
    assess_spatial_interval,
)
from src.application.analytics.temporal_continuity import (
    CadenceSource, ContinuityStatus, TemporalIntervalAssessment,
)


START = datetime(2026, 1, 1, 10)
GEOD = Geod(ellps="WGS84")


def pair(distance=0, seconds=15, accuracy=3, status=ContinuityStatus.CONTINUOUS):
    lon, lat, _ = GEOD.fwd(-65.472, -33.651, 90, distance)
    left = SpatialObservationRef(1, START, -33.651, -65.472, accuracy)
    right = SpatialObservationRef(2, START + timedelta(seconds=seconds), lat, lon, accuracy)
    temporal = TemporalIntervalAssessment(
        left.observed_at, right.observed_at, seconds, status, CadenceSource.NONE,
        None, None, None, None,
    )
    return left, right, temporal


class SpatialAssessmentTests(unittest.TestCase):
    def test_small_frequent_fix_is_compatible_not_proven_stationary(self):
        result = assess_spatial_interval(*pair(3, 15))
        self.assertEqual(result.status, SpatialIntervalStatus.STATIONARY_COMPATIBLE)
        self.assertEqual(result.reason, SpatialAssessmentReason.COMPATIBLE)
        self.assertAlmostEqual(result.distance_meters, 3, places=5)
        self.assertAlmostEqual(result.apparent_speed_mps, 0.2, places=5)
        self.assertEqual(result, assess_spatial_interval(*pair(3, 15)))

    def test_long_nearby_and_identical_fixes_are_uncertain(self):
        for distance in (0, 5):
            with self.subTest(distance=distance):
                result = assess_spatial_interval(*pair(distance, 600))
                self.assertEqual(result.reason, SpatialAssessmentReason.LONG_INTERVAL)

    def test_heatmap_config_can_assess_600_second_interval_without_changing_default(self):
        heatmap_config = SpatialAssessmentConfig(
            max_stationary_evidence_interval_seconds=600,
        )

        result = assess_spatial_interval(*pair(distance=0, seconds=600), config=heatmap_config)

        self.assertEqual(result.reason, SpatialAssessmentReason.COMPATIBLE)
        self.assertEqual(
            assess_spatial_interval(*pair(distance=0, seconds=600)).reason,
            SpatialAssessmentReason.LONG_INTERVAL,
        )

    def test_600_second_interval_still_requires_spatial_evidence(self):
        config = SpatialAssessmentConfig(max_stationary_evidence_interval_seconds=600)

        movement = assess_spatial_interval(*pair(distance=800, seconds=600), config=config)
        poor_accuracy = assess_spatial_interval(*pair(distance=0, seconds=600, accuracy=30), config=config)

        self.assertEqual(movement.reason, SpatialAssessmentReason.DISPLACEMENT)
        self.assertEqual(poor_accuracy.reason, SpatialAssessmentReason.INSUFFICIENT_ACCURACY)

    def test_significant_movement_and_implausible_jump_are_distinct(self):
        self.assertEqual(assess_spatial_interval(*pair(800, 600)).reason, SpatialAssessmentReason.DISPLACEMENT)
        self.assertEqual(assess_spatial_interval(*pair(20, 5, accuracy=1)).reason, SpatialAssessmentReason.DISPLACEMENT)
        jump = assess_spatial_interval(*pair(800, 5))
        self.assertEqual(jump.reason, SpatialAssessmentReason.IMPLAUSIBLE_JUMP)
        self.assertEqual(jump.status, SpatialIntervalStatus.SPATIALLY_UNCERTAIN)

    def test_bad_or_absent_accuracy_never_creates_dwell(self):
        for accuracy in (None, 30, 100, 255, -1, float("nan")):
            with self.subTest(accuracy=accuracy):
                result = assess_spatial_interval(*pair(0, 15, accuracy))
                self.assertEqual(result.reason, SpatialAssessmentReason.INSUFFICIENT_ACCURACY)

    def test_invalid_fix_is_temporally_present_but_spatially_uncertain(self):
        left, right, temporal = pair()
        for changes in ({"latitude": None}, {"longitude": 181}, {"latitude": float("nan")}):
            with self.subTest(changes=changes):
                result = assess_spatial_interval(left, replace(right, **changes), temporal)
                self.assertEqual(result.reason, SpatialAssessmentReason.INVALID_COORDINATE)
                self.assertIsNone(result.distance_meters)

    def test_uncertain_extent_and_temporal_status(self):
        self.assertEqual(assess_spatial_interval(*pair(10, 15, 10)).reason, SpatialAssessmentReason.AMBIGUOUS_POSITION)
        for status in (ContinuityStatus.GAP, ContinuityStatus.INDETERMINATE):
            self.assertEqual(assess_spatial_interval(*pair(status=status)).reason, SpatialAssessmentReason.TEMPORALLY_UNCERTAIN)

    def test_duplicate_and_microsecond_resolution(self):
        self.assertEqual(assess_spatial_interval(*pair(0, 0, status=ContinuityStatus.INDETERMINATE)).reason, SpatialAssessmentReason.TEMPORALLY_UNCERTAIN)
        result = assess_spatial_interval(*pair(0, 0.000001, accuracy=1))
        self.assertEqual(result.elapsed_seconds, 0.000001)
        self.assertEqual(result.status, SpatialIntervalStatus.STATIONARY_COMPATIBLE)

    def test_invalid_identity_timestamp_config_or_alignment(self):
        left, right, temporal = pair()
        invalid = (
            (replace(left, observation_id=2), right, temporal),
            (left, replace(right, observed_at=START), temporal),
            (left, right, replace(temporal, delta_seconds=9)),
            (left, right, replace(temporal, status="continuous")),
        )
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(SpatialAssessmentInputError):
                assess_spatial_interval(*args)
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(SpatialAssessmentInputError):
                SpatialAssessmentConfig(max_plausible_speed_mps=value)


if __name__ == "__main__":
    unittest.main()
