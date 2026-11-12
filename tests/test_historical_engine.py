import unittest
from datetime import datetime, timedelta

from src.application.analytics.historical_engine import RollingTemporalAnalyzer
from src.application.analytics.spatial_assessment import SpatialObservationRef
from src.application.analytics.temporal_continuity import analyze_temporal_continuity


START = datetime(2026, 1, 1)


class RollingTemporalTests(unittest.TestCase):
    def test_matches_unbounded_detector_across_batch_boundaries(self):
        for deltas in ((), (60,), (60,) * 10,
                       (5,) * 4 + (600,) * 5,
                       (60,) * 100 + (3600,) + (60,) * 100,
                       (60,) * 15 + (0, 0) + (60,) * 15):
            with self.subTest(deltas=deltas[:10]):
                stamps = [START]
                for delta in deltas:
                    stamps.append(stamps[-1] + timedelta(seconds=delta))
                engine = RollingTemporalAnalyzer()
                actual = []
                for index, stamp in enumerate(stamps):
                    actual.extend(item[2] for item in engine.feed(SpatialObservationRef(index + 1, stamp, 0, 0, 1)))
                    self.assertLessEqual(len(engine._buffer), 9)
                actual.extend(item[2] for item in engine.finish())
                self.assertEqual(tuple(actual), analyze_temporal_continuity(stamps))


if __name__ == "__main__":
    unittest.main()
