import unittest
from dataclasses import FrozenInstanceError, replace
from math import nextafter
from unittest.mock import Mock, patch

from pyproj import Geod, Transformer
from pyproj.exceptions import ProjError

from src.application.analytics.spatial_grid import (
    SpatialGridConfig,
    SpatialGridInputError,
    _axis_bounds,
    _cached_cell_geometry,
    _project_cached_cell,
    _projection,
    get_spatial_cell,
)


LATITUDE = -33.651
LONGITUDE = -65.472
PATCH_PROJECTION = "src.application.analytics.spatial_grid._projection"


class SpatialGridTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SpatialGridConfig("EPSG:32720", 25)
        self.forward = Transformer.from_crs(4326, 32720, always_xy=True)
        self.inverse = Transformer.from_crs(32720, 4326, always_xy=True)

    def _cell(self, latitude=LATITUDE, longitude=LONGITUDE, config=None):
        return get_spatial_cell(
            latitude=latitude, longitude=longitude,
            config=self.config if config is None else config,
        )

    def _from_projected(self, x: float, y: float):
        lon, lat = self.inverse.transform(x, y, errcheck=True)
        return self._cell(lat, lon)

    def test_known_argentina_point_and_axis_order(self) -> None:
        cell = self._cell()
        x, y = self.forward.transform(LONGITUDE, LATITUDE, errcheck=True)
        self.assertAlmostEqual(x, 270759.150510, places=5)
        self.assertAlmostEqual(y, 6273798.006026, places=5)
        self.assertEqual((cell.grid_x, cell.grid_y), (10830, 250951))
        self.assertEqual(cell.cell_id, "manea-grid:v1:EPSG:32720:25.0:10830:250951")
        with self.assertRaisesRegex(SpatialGridInputError, "area of use"):
            self._cell(LONGITUDE, LATITUDE)

    def test_internal_cached_geometry_matches_public_cell_exactly(self) -> None:
        for lat, lon in ((LATITUDE, LONGITUDE), (-33.651001, -65.472001),
                         (-33.65117215472983, -65.4633802423864)):
            with self.subTest(lat=lat, lon=lon):
                cached, x, y = _project_cached_cell(latitude=lat, longitude=lon, config=self.config)
                self.assertEqual(cached, self._cell(lat, lon))
                self.assertLessEqual(cached.x_min, x)
                self.assertLess(x, cached.x_max)
                self.assertLessEqual(cached.y_min, y)
                self.assertLess(y, cached.y_max)
        self.assertEqual(_cached_cell_geometry.cache_info().maxsize, 4096)

    def test_nearby_points_can_share_cell(self) -> None:
        self.assertEqual(self._cell(), self._cell(-33.651001, -65.472001))

    def test_nearby_points_can_cross_either_boundary(self) -> None:
        cell = self._cell()
        center_x = (cell.x_min + cell.x_max) / 2
        center_y = (cell.y_min + cell.y_max) / 2
        for axis in ("x", "y"):
            with self.subTest(axis=axis):
                if axis == "x":
                    before = self._from_projected(cell.x_max - 0.001, center_y)
                    after = self._from_projected(cell.x_max + 0.001, center_y)
                    self.assertEqual(after.grid_x, before.grid_x + 1)
                    self.assertEqual(after.grid_y, before.grid_y)
                else:
                    before = self._from_projected(center_x, cell.y_max - 0.001)
                    after = self._from_projected(center_x, cell.y_max + 0.001)
                    self.assertEqual(after.grid_y, before.grid_y + 1)
                    self.assertEqual(after.grid_x, before.grid_x)
                self.assertNotEqual(before.cell_id, after.cell_id)

    def test_distant_point_constructed_800_projected_meters_away(self) -> None:
        x, y = self.forward.transform(LONGITUDE, LATITUDE)
        lon, lat = self.inverse.transform(x + 800, y)
        distant = self._cell(lat, lon)
        self.assertEqual(distant.grid_x, self._cell().grid_x + 32)
        self.assertEqual(distant.grid_y, self._cell().grid_y)
        _, _, distance = Geod(ellps="WGS84").inv(LONGITUDE, LATITUDE, lon, lat)
        self.assertAlmostEqual(distance, 800, delta=1)

    def test_exact_projected_boundaries_are_half_open(self) -> None:
        # Test exact grid arithmetic separately from inverse/forward PROJ error.
        cases = (
            (0, 0, 0, 25),
            (12.5, 0, 0, 25),
            (25, 1, 25, 50),
            (nextafter(25, 0), 0, 0, 25),
            (nextafter(25, 50), 1, 25, 50),
            (-0.001, -1, -25, 0),
            (-25, -1, -25, 0),
            (-25.001, -2, -50, -25),
        )
        for coordinate, index, lower, upper in cases:
            with self.subTest(coordinate=coordinate):
                self.assertEqual(_axis_bounds(coordinate, 25), (index, lower, upper))

    def test_projected_center_corner_right_and_upper_edges(self) -> None:
        projection = _projection(self.config.crs)
        cell = self._cell()
        points = (
            ((cell.x_min + 12.5, cell.y_min + 12.5), (cell.grid_x, cell.grid_y)),
            ((cell.x_min, cell.y_min), (cell.grid_x, cell.grid_y)),
            ((cell.x_max, cell.y_min), (cell.grid_x + 1, cell.grid_y)),
            ((cell.x_min, cell.y_max), (cell.grid_x, cell.grid_y + 1)),
        )
        for point, expected in points:
            with self.subTest(point=point):
                # Force exact projected values; real inverse transform still runs.
                forward = Mock()
                forward.transform.return_value = point
                with patch(PATCH_PROJECTION, return_value=replace(projection, forward=forward)):
                    actual = self._cell()
                self.assertEqual((actual.grid_x, actual.grid_y), expected)

    def test_geographic_center_round_trip_is_geometric_metadata(self) -> None:
        cell = self._cell()
        self.assertEqual(self._cell(cell.center_latitude, cell.center_longitude), cell)
        x, y = self.forward.transform(cell.center_longitude, cell.center_latitude)
        self.assertAlmostEqual(x, cell.x_min + 12.5, places=6)
        self.assertAlmostEqual(y, cell.y_min + 12.5, places=6)
        self.assertNotEqual((cell.center_latitude, cell.center_longitude), (LATITUDE, LONGITUDE))

    def test_stability_across_orders_and_unrelated_points(self) -> None:
        points = [(LATITUDE, LONGITUDE), (-33.652, -65.473), (-34, -64)]
        first = {point: self._cell(*point).cell_id for point in points}
        self._cell(-40, -62)
        second = {point: self._cell(*point).cell_id for point in reversed(points)}
        self.assertEqual(first, second)

    def test_different_resolutions_have_distinct_identities(self) -> None:
        cells = [self._cell(config=SpatialGridConfig("EPSG:32720", size)) for size in (10, 25, 50, 100, 25.0000000001)]
        self.assertEqual(len({cell.cell_id for cell in cells}), len(cells))
        for cell in cells:
            self.assertAlmostEqual(cell.x_max - cell.x_min, cell.cell_size_meters, places=8)
            self.assertAlmostEqual(cell.y_max - cell.y_min, cell.cell_size_meters, places=8)

    def test_equivalent_configuration_is_canonical_and_immutable(self) -> None:
        other = SpatialGridConfig("epsg:32720", 25.0)
        self.assertEqual(self.config, other)
        self.assertEqual(self._cell(), self._cell(config=other))
        with self.assertRaises(FrozenInstanceError):
            other.cell_size_meters = 50
        with self.assertRaises(FrozenInstanceError):
            self._cell().grid_x = 1

    def test_different_crs_have_distinct_identities_at_shared_zone_boundary(self) -> None:
        west = self._cell(-33, -66, SpatialGridConfig("EPSG:32719", 25))
        east = self._cell(-33, -66, SpatialGridConfig("EPSG:32720", 25))
        self.assertNotEqual(west.cell_id, east.cell_id)
        self.assertNotEqual(west.crs, east.crs)

    def test_argentina_regions_use_explicit_different_zones(self) -> None:
        for lat, lon, epsg in ((-50, -73, 32718), (-40, -70, 32719), (-33, -65, 32720), (-35, -58, 32721), (-26, -53.8, 32722)):
            with self.subTest(epsg=epsg):
                config = SpatialGridConfig(f"EPSG:{epsg}", 25)
                self.assertEqual(self._cell(lat, lon, config).crs, config.crs)

    def test_identity_can_reconstruct_config_indices_and_bounds(self) -> None:
        original = self._cell()
        namespace, version, authority, code, size, gx, gy = original.cell_id.split(":")
        self.assertEqual((namespace, version), ("manea-grid", "v1"))
        reconstructed = SpatialGridConfig(f"{authority}:{code}", float(size))
        self.assertEqual(reconstructed, self.config)
        self.assertEqual(int(gx) * reconstructed.cell_size_meters, original.x_min)
        self.assertEqual((int(gy) + 1) * reconstructed.cell_size_meters, original.y_max)

    def test_containment_size_alignment_properties(self) -> None:
        for latitude in (-25, -33.651, -40, -54):
            for longitude in (-65.9, -65.472, -63, -60.1):
                for size in (10, 25, 50, 100):
                    with self.subTest(lat=latitude, lon=longitude, size=size):
                        cell = self._cell(latitude, longitude, SpatialGridConfig("EPSG:32720", size))
                        x, y = self.forward.transform(longitude, latitude)
                        self.assertLessEqual(cell.x_min, x)
                        self.assertLess(x, cell.x_max)
                        self.assertLessEqual(cell.y_min, y)
                        self.assertLess(y, cell.y_max)
                        self.assertEqual(cell.x_min, cell.grid_x * size)
                        self.assertEqual(cell.y_min, cell.grid_y * size)
                        self.assertEqual(cell.x_max - cell.x_min, size)
                        self.assertEqual(cell.y_max - cell.y_min, size)

    def test_invalid_coordinates_are_rejected(self) -> None:
        invalid = (True, False, "-33", None, float("nan"), float("inf"), -float("inf"), 10**1000)
        for value in invalid:
            for field in ("latitude", "longitude"):
                with self.subTest(field=field, value=value), self.assertRaises(SpatialGridInputError):
                    self._cell(**{field: value})
        for lat, lon in ((-91, -65), (91, -65), (-33, -181), (-33, 181)):
            with self.subTest(lat=lat, lon=lon), self.assertRaises(SpatialGridInputError):
                self._cell(lat, lon)

    def test_outside_crs_area_is_rejected_without_zone_switch(self) -> None:
        for lat, lon in ((-33, -66.0001), (-33, -59.9999), (0.001, -63), (-80.001, -63)):
            with self.subTest(lat=lat, lon=lon), self.assertRaisesRegex(SpatialGridInputError, "area of use"):
                self._cell(lat, lon)

    def test_invalid_sizes_are_rejected(self) -> None:
        for size in (0, -1, True, "25", None, float("nan"), float("inf"), 10**1000):
            with self.subTest(size=size), self.assertRaises(SpatialGridInputError):
                SpatialGridConfig("EPSG:32720", size)

    def test_invalid_or_incompatible_crs_are_rejected(self) -> None:
        for crs in (None, True, 32720, "", "not-a-crs", "EPSG:999999", "EPSG:4326", "EPSG:3857", "EPSG:32620", "EPSG:4978", "EPSG:2277"):
            with self.subTest(crs=crs), self.assertRaises(SpatialGridInputError):
                SpatialGridConfig(crs, 25)
        with self.assertRaises(SpatialGridInputError):
            get_spatial_cell(latitude=LATITUDE, longitude=LONGITUDE, config=None)

    def test_unrepresentable_resolution_is_controlled_error(self) -> None:
        for size in (5e-324, 1e-20, 1e308):
            with self.subTest(size=size), self.assertRaises(SpatialGridInputError):
                self._cell(config=SpatialGridConfig("EPSG:32720", size))

    def test_transform_failures_and_nonfinite_results_are_rejected(self) -> None:
        projection = _projection(self.config.crs)
        for direction in ("forward", "inverse"):
            for output in (ProjError("test failure"), (float("inf"), 0), (0, float("nan"))):
                transformer = Mock()
                if isinstance(output, Exception):
                    transformer.transform.side_effect = output
                else:
                    transformer.transform.return_value = output
                with self.subTest(direction=direction, output=output):
                    with patch(PATCH_PROJECTION, return_value=replace(projection, **{direction: transformer})):
                        with self.assertRaises(SpatialGridInputError):
                            self._cell()


if __name__ == "__main__":
    unittest.main()
