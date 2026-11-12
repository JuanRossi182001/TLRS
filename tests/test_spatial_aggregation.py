import unittest
from dataclasses import replace
from datetime import datetime, timedelta

from pyproj import Transformer

from src.application.analytics.observation_attribution import ContributionSide
from src.application.analytics.observation_bucketing import ObservationBucketContribution
from src.application.analytics.spatial_aggregation import aggregate_spatial_time, SpatialAggregationInputError
from src.application.analytics.spatial_assessment import SpatialObservationRef, SpatialIntervalStatus, SpatialAssessmentReason
from src.application.analytics.spatial_grid import SpatialGridConfig, get_spatial_cell
from src.application.analytics.spatial_qualification import SpatialQualificationResult, SpatialQualificationMetadata, SpatiallyQualifiedContribution


START = datetime(2026, 1, 1, 10)
CONFIG = SpatialGridConfig("EPSG:32720", 25)


def make_item(observation_id, start, seconds, status=SpatialIntervalStatus.STATIONARY_COMPATIBLE, index=0):
    part = ObservationBucketContribution(observation_id, index, START, START + timedelta(minutes=5),
                                         start, start + timedelta(seconds=seconds), seconds, ContributionSide.LEFT)
    return SpatiallyQualifiedContribution(part, status, SpatialAssessmentReason.COMPATIBLE,
                                          status == SpatialIntervalStatus.STATIONARY_COMPATIBLE)


def qualify(items):
    total = sum(c.source.observed_seconds for c in items)
    eligible = sum(c.source.observed_seconds for c in items if c.eligible_for_dwell)
    displaced = sum(c.source.observed_seconds for c in items if c.spatial_status == SpatialIntervalStatus.DISPLACEMENT)
    return SpatialQualificationResult(tuple(items), SpatialQualificationMetadata(total, eligible, displaced, total - eligible - displaced))


class SpatialAggregationTests(unittest.TestCase):
    def test_one_cell_and_distinct_observations(self):
        observations = {1: SpatialObservationRef(1, START, -33.651, -65.472, 1),
                        2: SpatialObservationRef(2, START, -33.651001, -65.472001, 1)}
        items = [make_item(1, START, 15), make_item(2, START + timedelta(seconds=15), 15, index=1)]
        result = aggregate_spatial_time(asset_id=3, qualified=qualify(items), observations=observations, config=CONFIG)
        self.assertEqual(result.metadata.dwell_seconds, 30)
        self.assertEqual(len(result.buckets), 1)
        self.assertEqual(result.buckets[0].observation_count, 2)
        self.assertEqual(result.buckets[0].asset_id, 3)
        self.assertEqual(result, aggregate_spatial_time(asset_id=3, qualified=qualify(items), observations=observations, config=CONFIG))

    def test_two_distant_cells_and_excluded_seconds(self):
        xform = Transformer.from_crs(4326, CONFIG.crs, always_xy=True)
        inverse = Transformer.from_crs(CONFIG.crs, 4326, always_xy=True)
        x, y = xform.transform(-65.472, -33.651)
        lon, lat = inverse.transform(x + 800, y)
        observations = {1: SpatialObservationRef(1, START, -33.651, -65.472, 1),
                        2: SpatialObservationRef(2, START, lat, lon, 1)}
        items = [make_item(1, START, 10), make_item(2, START + timedelta(seconds=10), 10, index=1),
                 make_item(2, START + timedelta(seconds=20), 5, SpatialIntervalStatus.DISPLACEMENT, index=2),
                 make_item(2, START + timedelta(seconds=25), 5, SpatialIntervalStatus.SPATIALLY_UNCERTAIN, index=3)]
        result = aggregate_spatial_time(asset_id=3, qualified=qualify(items), observations=observations, config=CONFIG)
        self.assertEqual(len(result.buckets), 2)
        self.assertNotEqual(result.buckets[0].cell.cell_id, result.buckets[1].cell.cell_id)
        self.assertEqual(result.metadata.dwell_seconds, 20)
        self.assertEqual(result.metadata.observed_seconds, 30)
        self.assertEqual(result.metadata.displacement_seconds, 5)
        self.assertEqual(result.metadata.spatially_uncertain_seconds, 5)
        with self.assertRaisesRegex(SpatialAggregationInputError, "limit"):
            aggregate_spatial_time(asset_id=3, qualified=qualify(items), observations=observations, config=CONFIG, max_cells=1)

    def test_boundary_accuracy_is_not_assigned(self):
        cell = get_spatial_cell(latitude=-33.651, longitude=-65.472, config=CONFIG)
        lon, lat = Transformer.from_crs(CONFIG.crs, 4326, always_xy=True).transform(cell.x_max - 1, (cell.y_min + cell.y_max) / 2)
        observations = {1: SpatialObservationRef(1, START, lat, lon, 3)}
        result = aggregate_spatial_time(asset_id=3, qualified=qualify((make_item(1, START, 10),)), observations=observations, config=CONFIG)
        self.assertEqual(result.buckets, ())
        self.assertEqual(result.metadata.cell_boundary_uncertain_seconds, 10)
        self.assertEqual(result.metadata.other_excluded_seconds, 10)

    def test_outside_crs_is_accounted_for(self):
        observations = {1: SpatialObservationRef(1, START, -33, -69, 1)}
        result = aggregate_spatial_time(asset_id=3, qualified=qualify((make_item(1, START, 10),)), observations=observations, config=CONFIG)
        self.assertEqual(result.metadata.outside_grid_seconds, 10)
        self.assertEqual(result.metadata.dwell_seconds, 0)

    def test_reject_missing_observation_or_bad_metadata(self):
        items = qualify((make_item(1, START, 10),))
        with self.assertRaises(SpatialAggregationInputError):
            aggregate_spatial_time(asset_id=3, qualified=items, observations={}, config=CONFIG)
        with self.assertRaises(SpatialAggregationInputError):
            aggregate_spatial_time(asset_id=3, qualified=replace(items, metadata=replace(items.metadata, observed_seconds=11)),
                                   observations={1: SpatialObservationRef(1, START, -33.651, -65.472, 1)}, config=CONFIG)
        with self.assertRaises(SpatialAggregationInputError):
            aggregate_spatial_time(asset_id=3, qualified=items,
                                   observations={1: SpatialObservationRef(1, START, -33.651, -65.472, 1)},
                                   config=SpatialGridConfig("EPSG:32720", 1e-20))


if __name__ == "__main__":
    unittest.main()
