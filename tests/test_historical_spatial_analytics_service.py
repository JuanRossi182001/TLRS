import unittest
from datetime import datetime, timedelta

from pyproj import Transformer

from src.application.analytics.historical_assignment import AssignmentRef, AssignmentHistoryInputError
from src.application.analytics.spatial_assessment import SpatialObservationRef
from src.application.analytics.spatial_assessment import SpatialAssessmentConfig
from src.application.analytics.performance_profile import ProcessingProfile
from src.application.analytics.spatial_grid import SpatialGridConfig
from src.service.historical_spatial_analytics_service import (
    HistoricalAnalyticsLimitExceeded, HistoricalAnalyticsNotFound,
    HistoricalSpatialAnalyticsService, HistoricalAnalyticsLimits,
)


START = datetime(2026, 1, 1, 10)
GRID = SpatialGridConfig("EPSG:32720", 25)


def series(deltas, *, device=1, offset=0, first_id=1, latitude=-33.651, longitude=-65.472, accuracy=1):
    times = [START + timedelta(seconds=offset)]
    for delta in deltas:
        times.append(times[-1] + timedelta(seconds=delta))
    return tuple(SpatialObservationRef(first_id + i, t, latitude, longitude, accuracy)
                 for i, t in enumerate(times))


def assignment(assignment_id, asset, device, start=0, end=None):
    return AssignmentRef(assignment_id, asset, device, START + timedelta(seconds=start),
                         None if end is None else START + timedelta(seconds=end))


class FakeRepository:
    def __init__(self, assignments, locations, *, accessible=(1,), group=(1,), estimate_count=0):
        self.history = assignments
        self.locations = locations
        self.accessible = set(accessible)
        self.group = group
        self.estimate_count = estimate_count
        self.requested = []

    async def estimate_location_count(self, *, client_id, asset_ids, window_start, window_end, limit):
        self.requested.append(("estimate", client_id, tuple(asset_ids), limit))
        return min(self.estimate_count, limit)

    async def accessible_asset_ids(self, *, client_id, asset_ids):
        self.requested.append(("assets", client_id, tuple(asset_ids)))
        return set(asset_ids) & self.accessible if client_id == 17 else set()

    async def group_asset_ids(self, *, client_id, group_id, limit):
        return tuple(self.group[:limit]) if client_id == 17 and group_id == 3 else None

    async def assignments(self, *, client_id, asset_ids, window_start, window_end, limit):
        self.requested.append(("history", client_id, tuple(asset_ids)))
        return tuple(x for x in self.history if x.assigned_at < window_end
                     and (x.unassigned_at is None or x.unassigned_at > window_start))[:limit]

    def _rows(self, assignment):
        return sorted((o for o in self.locations.get(assignment.device_id, ())
                       if o.observed_at >= assignment.assigned_at
                       and (assignment.unassigned_at is None or o.observed_at < assignment.unassigned_at)),
                      key=lambda o: (o.observed_at, o.observation_id))

    async def neighboring_locations(self, assignment, *, boundary, before, count=5):
        rows = [o for o in self._rows(assignment) if (o.observed_at < boundary if before else o.observed_at >= boundary)]
        return tuple(rows[-count:] if before else rows[:count])

    async def iter_locations(self, assignment, *, start, end, page_size):
        self.requested.append(("locations", assignment.asset_id, assignment.device_id, page_size))
        for o in self._rows(assignment):
            if start <= o.observed_at < end:
                yield o


class HistoricalAnalyticsServiceTests(unittest.IsolatedAsyncioTestCase):
    def _service(self, assignments, locations, **kwargs):
        repo = FakeRepository(assignments, locations, **kwargs)
        return HistoricalSpatialAnalyticsService(None, repository=repo), repo

    async def _run(self, service, *, assets=(1,), start=0, end=600, limits=HistoricalAnalyticsLimits()):
        return await service.analyze_assets(
            client_id=17, asset_ids=assets, window_start=START + timedelta(seconds=start),
            window_end=START + timedelta(seconds=end), grid_config=GRID, limits=limits,
        )

    async def test_stationary_with_partial_window_and_neighbors(self):
        observations = series([15] * 20)
        service, repo = self._service((assignment(1, 1, 1, 0, 400),), {1: observations})
        result = await self._run(service, start=22, end=278)
        m = result.metadata
        self.assertEqual(m.observed_seconds, 256)
        self.assertEqual(m.dwell_seconds, 256)
        self.assertEqual(m.eligible_assignment_seconds, 256)
        self.assertEqual(m.temporal_coverage_ratio, 1)
        self.assertEqual(m.raw_location_count, 17)
        self.assertGreater(m.processed_location_count, m.raw_location_count)
        self.assertEqual(sum(b.dwell_seconds for b in result.buckets), 256)
        self.assertEqual(len({b.spatial_cell_id for b in result.buckets}), 1)
        self.assertGreater(result.buckets[0].observation_count, 0)
        self.assertIsNone(result.buckets[0].observation_ids)
        self.assertTrue(all(b.asset_id == 1 for b in result.buckets))
        self.assertTrue(all(req[1] == 17 for req in repo.requested if req[0] in ("assets", "history")))
        self.assertEqual(result, await self._run(service, start=22, end=278))

    async def test_600_second_reports_can_contribute_dwell_with_heatmap_spatial_config(self):
        observations = series([600] * 12, offset=-600, accuracy=1)
        service, _ = self._service((assignment(1, 1, 1, -600, 6600),), {1: observations})

        result = await service.analyze_asset(
            client_id=17,
            asset_id=1,
            window_start=START,
            window_end=START + timedelta(seconds=6000),
            grid_config=GRID,
            assessment_config=SpatialAssessmentConfig(
                max_stationary_evidence_interval_seconds=600,
            ),
        )

        self.assertEqual(result.metadata.observed_seconds, 6000)
        self.assertEqual(result.metadata.dwell_seconds, 6000)
        self.assertEqual(sum(bucket.dwell_seconds for bucket in result.buckets), 6000)
        self.assertEqual(len({bucket.spatial_cell_id for bucket in result.buckets}), 1)

    async def test_optional_profile_does_not_change_results(self):
        observations = series([15] * 20)
        service, repo = self._service((assignment(1, 1, 1, 0, 400),), {1: observations})
        expected = await self._run(service, start=22, end=278)
        profile = ProcessingProfile()
        measured = HistoricalSpatialAnalyticsService(None, repository=repo, profile=profile)
        self.assertEqual(expected, await self._run(measured, start=22, end=278))
        self.assertEqual(profile.locations_processed, expected.metadata.processed_location_count)
        self.assertEqual(profile.result_count, len(expected.buckets))
        self.assertGreater(profile.continuity_seconds, 0)
        self.assertGreater(profile.grid_seconds, 0)
        self.assertGreater(profile.total_seconds, profile.grid_seconds)
        self.assertGreaterEqual(profile.other_seconds, 0)
        self.assertEqual(expected, await self._run(measured, start=22, end=278))
        self.assertEqual(profile.result_count, len(expected.buckets))

    async def test_gap_cadence_duplicate_and_no_fix(self):
        for deltas, expected in (([60] * 4 + [3600] + [60] * 4, 480),
                                 ([5] * 4 + [600] * 5, 2415),
                                 ([60] * 4 + [0] + [60] * 5, 540)):
            with self.subTest(deltas=deltas):
                observations = series(deltas)
                service, _ = self._service((assignment(1, 1, 1, 0, 8000),), {1: observations})
                m = (await self._run(service, end=8000)).metadata
                self.assertEqual(m.observed_seconds, expected)
                self.assertEqual(m.dwell_seconds + m.displacement_seconds
                                 + m.spatially_uncertain_seconds + m.other_excluded_seconds, expected)
                self.assertLessEqual(m.dwell_seconds, expected)
        observations = series([15] * 10, accuracy=255)
        service, _ = self._service((assignment(1, 1, 1, 0, 300),), {1: observations})
        m = (await self._run(service, end=300)).metadata
        self.assertEqual(m.observed_seconds, 150)
        self.assertEqual(m.dwell_seconds, 0)
        self.assertEqual(m.spatially_uncertain_seconds, 150)
        self.assertEqual(m.eligible_location_count, 0)

    async def test_two_zones_have_no_fake_midpoint_heat(self):
        original = series([15] * 120)
        forward = Transformer.from_crs(4326, GRID.crs, always_xy=True)
        inverse = Transformer.from_crs(GRID.crs, 4326, always_xy=True)
        x, y = forward.transform(-65.472, -33.651)
        lon, lat = inverse.transform(x + 800, y)
        other = series([15] * 120, offset=1815, first_id=1000, latitude=lat, longitude=lon)
        service, _ = self._service((assignment(1, 1, 1, 0, 4000),), {1: original + other})
        result = await self._run(service, end=3630)
        cells = {b.spatial_cell_id for b in result.buckets}
        self.assertEqual(len(cells), 2)
        self.assertEqual(result.metadata.spatially_uncertain_seconds, 15)
        self.assertEqual(result.metadata.dwell_seconds, 3600)
        self.assertLess(result.metadata.dwell_seconds, result.metadata.observed_seconds)
        with self.assertRaises(HistoricalAnalyticsLimitExceeded):
            await self._run(service, end=3630, limits=HistoricalAnalyticsLimits(max_cells=1))

    async def test_progressive_movement_does_not_create_dwell(self):
        forward = Transformer.from_crs(4326, GRID.crs, always_xy=True)
        inverse = Transformer.from_crs(GRID.crs, 4326, always_xy=True)
        x, y = forward.transform(-65.472, -33.651)
        observations = []
        for index in range(11):
            lon, lat = inverse.transform(x + 25 * index, y)
            observations.append(SpatialObservationRef(
                index + 1, START + timedelta(seconds=15 * index), lat, lon, 1
            ))
        service, _ = self._service((assignment(1, 1, 1, 0, 200),), {1: observations})
        result = await self._run(service, end=150)
        self.assertEqual(result.metadata.observed_seconds, 150)
        self.assertEqual(result.metadata.displacement_seconds, 150)
        self.assertEqual(result.metadata.dwell_seconds, 0)
        self.assertEqual(result.buckets, ())

    async def test_invalid_location_remains_temporal_evidence(self):
        observations = list(series([15] * 10))
        bad = observations[5]
        observations[5] = SpatialObservationRef(bad.observation_id, bad.observed_at, float("nan"),
                                                bad.longitude, bad.accuracy_meters)
        service, _ = self._service((assignment(1, 1, 1, 0, 200),), {1: observations})
        result = await self._run(service, end=150)
        self.assertEqual(result.metadata.observed_seconds, 150)
        self.assertEqual(result.metadata.spatially_uncertain_seconds, 30)
        self.assertEqual(result.metadata.eligible_location_count, 9)
        self.assertEqual(result.metadata.dwell_seconds, 120)

    async def test_reassignment_never_crosses_animals(self):
        # The device pointer could currently target asset 2; only history matters.
        first = series([15] * 10)
        second = series([15] * 10, offset=300, first_id=100)
        service, _ = self._service((assignment(1, 1, 1, 0, 200), assignment(2, 2, 1, 300, 500)),
                                    {1: first + second}, accessible=(1, 2), group=(1, 2))
        result = await self._run(service, assets=(1, 2), end=500)
        self.assertEqual(result.metadata.dwell_seconds, 300)
        self.assertEqual(result.metadata.eligible_assignment_seconds, 400)
        self.assertEqual({b.asset_id for b in result.buckets}, {1, 2})
        self.assertEqual(result.metadata.asset_count, 2)
        group = await service.analyze_asset_group(
            client_id=17, group_id=3, window_start=START, window_end=START + timedelta(seconds=500), grid_config=GRID,
        )
        self.assertEqual(group.buckets, result.buckets)

    async def test_simultaneous_animals_accumulate_animal_seconds(self):
        service, _ = self._service((assignment(1, 1, 1, 0, 300), assignment(2, 2, 2, 0, 300)),
                                   {1: series([15] * 10), 2: series([15] * 10, first_id=100)}, accessible=(1, 2))
        result = await self._run(service, assets=(1, 2), end=150)
        self.assertEqual(result.metadata.dwell_seconds, 300)
        self.assertEqual(sum(b.dwell_seconds for b in result.buckets), 300)
        self.assertEqual(len({b.spatial_cell_id for b in result.buckets}), 1)
        per_asset = {asset: sum(b.dwell_seconds for b in result.buckets if b.asset_id == asset)
                     for asset in (1, 2)}
        self.assertEqual(per_asset, {1: 150, 2: 150})

    async def test_empty_no_history_and_limits_are_controlled(self):
        service, _ = self._service((), {})
        empty = await self._run(service)
        self.assertIsNone(empty.metadata.temporal_coverage_ratio)
        self.assertEqual(empty.metadata.dwell_seconds, 0)
        service, _ = self._service((assignment(1, 1, 1, 0),), {1: series([15] * 10)})
        with self.assertRaises(HistoricalAnalyticsLimitExceeded):
            await self._run(service, limits=HistoricalAnalyticsLimits(max_locations=3))
        with self.assertRaises(HistoricalAnalyticsLimitExceeded):
            await self._run(service, limits=HistoricalAnalyticsLimits(max_fragments=1))
        with self.assertRaises(HistoricalAnalyticsLimitExceeded):
            await self._run(service, limits=HistoricalAnalyticsLimits(max_results=1))
        with self.assertRaises(HistoricalAnalyticsNotFound):
            await service.analyze_asset(client_id=18, asset_id=1, window_start=START,
                                        window_end=START + timedelta(seconds=600), grid_config=GRID)

    async def test_group_authorization_and_location_preflight_limit(self):
        service, repo = self._service((), {}, group=(1, 2), accessible=(1, 2))
        with self.assertRaises(HistoricalAnalyticsNotFound):
            await service.analyze_asset_group(
                client_id=18, group_id=3, window_start=START,
                window_end=START + timedelta(seconds=600), grid_config=GRID,
            )

        repo.estimate_count = 4
        limited = HistoricalAnalyticsLimits(max_locations=3)
        with self.assertRaisesRegex(HistoricalAnalyticsLimitExceeded, "Estimated location limit"):
            await self._run(service, end=600, limits=limited)
        self.assertFalse(any(item[0] == "locations" for item in repo.requested))

    async def test_overlap_is_rejected_even_if_other_asset_not_requested(self):
        service, _ = self._service((assignment(1, 1, 1, 0, 100), assignment(2, 2, 1, 50, 150)),
                                   {1: series([15] * 10)}, accessible=(1, 2))
        with self.assertRaises(AssignmentHistoryInputError):
            await self._run(service, assets=(1,), end=100)

    async def test_hundred_animal_month_rejects_before_unbounded_processing(self):
        class GeneratedRepository(FakeRepository):
            async def neighboring_locations(self, assignment, *, boundary, before, count=5):
                return ()

            async def iter_locations(self, assignment, *, start, end, page_size):
                for index in range(30 * 96):
                    stamp = START + timedelta(minutes=15 * index)
                    if start <= stamp < end:
                        yield SpatialObservationRef(
                            assignment.device_id * 10000 + index, stamp, -33.651, -65.472, 1
                        )

        repo = GeneratedRepository(
            tuple(assignment(i, i, i, 0, 30 * 86400) for i in range(1, 101)), {},
            accessible=range(1, 101),
        )
        service = HistoricalSpatialAnalyticsService(None, repository=repo)
        with self.assertRaisesRegex(HistoricalAnalyticsLimitExceeded, "location limit"):
            await self._run(service, assets=tuple(range(1, 101)), end=30 * 86400,
                            limits=HistoricalAnalyticsLimits(max_locations=1000, max_query_seconds=300))


if __name__ == "__main__":
    unittest.main()
