import unittest
from dataclasses import replace
from datetime import datetime, timedelta

from src.application.analytics.observation_attribution import ContributionSide, TemporalObservationRef, attribute_observed_time_to_observations
from src.application.analytics.observation_bucketing import bucket_observation_contributions
from src.application.analytics.spatial_assessment import SpatialObservationRef, assess_spatial_interval, SpatialIntervalStatus
from src.application.analytics.spatial_qualification import (
    qualify_observed_time, SpatialQualificationInputError, _qualify_generated_interval,
)
from src.application.analytics.temporal_continuity import CadenceSource, ContinuityStatus, TemporalIntervalAssessment


START = datetime(2026, 1, 1, 10)


def pipeline(status=ContinuityStatus.CONTINUOUS, distance=0, accuracy=1, end=180):
    from pyproj import Geod
    longitude, latitude, _ = Geod(ellps="WGS84").fwd(-65.472, -33.651, 90, distance)
    refs = (SpatialObservationRef(1, START, -33.651, -65.472, accuracy),
            SpatialObservationRef(2, START + timedelta(seconds=end), latitude, longitude, accuracy))
    temporal = (TemporalIntervalAssessment(START, refs[-1].observed_at, end, status, CadenceSource.NONE, None, None, None, None),)
    spatial = (assess_spatial_interval(*refs, temporal[0]),)
    attribution = attribute_observed_time_to_observations(
        tuple(TemporalObservationRef(o.observation_id, o.observed_at) for o in refs), temporal,
    )
    fragments = bucket_observation_contributions(
        contributions=attribution.contributions, window_start=START,
        window_end=refs[-1].observed_at, bucket_seconds=60,
    ).contributions
    return temporal, spatial, fragments


class SpatialQualificationTests(unittest.TestCase):
    def test_generated_fast_path_matches_public_reference(self):
        for duration, distance, accuracy in ((30, 0, 1), (30, 80, 1),
                                             (600, 0, 1), (30, 0, 255),
                                             (0.000001, 0, 1)):
            with self.subTest(duration=duration, distance=distance, accuracy=accuracy):
                time, spatial, _ = pipeline(distance=distance, accuracy=accuracy, end=duration)
                for offset in (0, duration / 4):
                    start = START + timedelta(seconds=offset)
                    finish = START + timedelta(seconds=duration * 3 / 4) if offset else START + timedelta(seconds=duration)
                    if start >= finish:
                        continue
                    chunks = bucket_observation_contributions(
                        contributions=attribute_observed_time_to_observations(
                            (TemporalObservationRef(1, START), TemporalObservationRef(2, START + timedelta(seconds=duration))),
                            time,
                        ).contributions,
                        window_start=start, window_end=finish, bucket_seconds=60,
                    ).contributions
                    expected = qualify_observed_time(contributions=chunks, temporal=time,
                                                     spatial=spatial, window_start=start, window_end=finish)
                    actual = _qualify_generated_interval(contributions=chunks, temporal=time[0],
                                                         spatial=spatial[0], window_start=start, window_end=finish)
                    self.assertEqual(expected, actual)
    def test_eligible_displaced_and_uncertain_conserve_per_bucket(self):
        for distance, accuracy, expected in ((0, 1, "spatially_eligible_seconds"),
                                             (80, 1, "displacement_seconds"),
                                             (0, 255, "spatially_uncertain_seconds")):
            with self.subTest(distance=distance, accuracy=accuracy):
                temporal, spatial, fragments = pipeline(distance=distance, accuracy=accuracy, end=30)
                result = qualify_observed_time(contributions=fragments, temporal=temporal, spatial=spatial,
                                               window_start=START, window_end=START + timedelta(seconds=30))
                self.assertEqual(result.metadata.observed_seconds, 30)
                self.assertEqual(getattr(result.metadata, expected), 30)
                self.assertEqual(sum((result.metadata.spatially_eligible_seconds,
                                      result.metadata.displacement_seconds,
                                      result.metadata.spatially_uncertain_seconds)), 30)
                self.assertEqual(sum(c.source.observed_seconds for c in result.contributions), 30)
                self.assertTrue(all(c.source.interval_index == 0 for c in result.contributions))

    def test_clipped_multibucket_long_transition_and_gap(self):
        temporal, spatial, fragments = pipeline(distance=0, accuracy=1, end=600)
        result = qualify_observed_time(
            contributions=bucket_observation_contributions(
                contributions=attribute_observed_time_to_observations(
                    (TemporalObservationRef(1, START), TemporalObservationRef(2, START + timedelta(seconds=600))), temporal,
                ).contributions,
                window_start=START + timedelta(seconds=40), window_end=START + timedelta(seconds=560), bucket_seconds=60,
            ).contributions,
            temporal=temporal, spatial=spatial,
            window_start=START + timedelta(seconds=40), window_end=START + timedelta(seconds=560),
        )
        self.assertEqual(result.metadata.spatially_uncertain_seconds, 520)
        self.assertEqual(result.metadata.observed_seconds, 520)
        temporal, spatial, fragments = pipeline(status=ContinuityStatus.GAP)
        self.assertEqual(qualify_observed_time(contributions=fragments, temporal=temporal, spatial=spatial,
                                              window_start=START, window_end=START + timedelta(seconds=180)).metadata.observed_seconds, 0)

    def test_reject_missing_overlap_wrong_identity_or_inconsistent_status(self):
        temporal, spatial, fragments = pipeline(end=30)
        window_end = START + timedelta(seconds=30)
        for changes in (fragments[:-1], fragments + (fragments[0],),
                        (replace(fragments[0], observation_id=7),) + fragments[1:],
                        (replace(fragments[0], observation_id=2, side=ContributionSide.RIGHT),) + fragments[1:],
                        (replace(fragments[0], contribution_start=START + timedelta(seconds=1)),) + fragments[1:]):
            with self.subTest(changes=changes), self.assertRaises(SpatialQualificationInputError):
                qualify_observed_time(contributions=changes, temporal=temporal, spatial=spatial,
                                      window_start=START, window_end=window_end)
        with self.assertRaises(SpatialQualificationInputError):
            qualify_observed_time(contributions=fragments, temporal=temporal,
                                  spatial=(replace(spatial[0], interval_end=START),),
                                  window_start=START, window_end=window_end)


if __name__ == "__main__":
    unittest.main()
