"""Fixed-origin metric grids in explicitly selected WGS84 / UTM South CRSs.

Cells are half-open in projected metres, not degrees. A cell's geographic center
is geometric metadata, never an observed animal position. No temporal or ORM
contracts participate in this module.
"""

from dataclasses import dataclass
from functools import lru_cache
from math import floor, isfinite

from pyproj import CRS, Transformer
from pyproj.exceptions import ProjError


class SpatialGridInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Projection:
    crs: CRS
    forward: Transformer
    inverse: Transformer


@lru_cache(maxsize=128)
def _projection(crs_text: str) -> _Projection:
    try:
        crs = CRS.from_user_input(crs_text)
        epsg = crs.to_epsg()
        if (
            epsg is None
            or not 32701 <= epsg <= 32760
            or not crs.equals(CRS.from_epsg(epsg))
            or not crs.is_projected
            or len(crs.axis_info) != 2
            or any(axis.unit_conversion_factor != 1 for axis in crs.axis_info)
            or crs.area_of_use is None
        ):
            raise SpatialGridInputError("CRS must be an EPSG WGS84 / UTM South metric CRS.")
        return _Projection(
            crs=crs,
            forward=Transformer.from_crs(
                "EPSG:4326", crs, always_xy=True, allow_ballpark=False, only_best=True
            ),
            inverse=Transformer.from_crs(
                crs, "EPSG:4326", always_xy=True, allow_ballpark=False, only_best=True
            ),
        )
    except ProjError as exc:
        raise SpatialGridInputError("CRS cannot provide the required WGS84 transformation.") from exc


def _finite_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpatialGridInputError(f"{name} must be a finite number, excluding booleans.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise SpatialGridInputError(f"{name} must be a finite number.") from exc
    if not isfinite(number):
        raise SpatialGridInputError(f"{name} must be a finite number.")
    return number


@dataclass(frozen=True, slots=True)
class SpatialGridConfig:
    crs: str
    cell_size_meters: float

    def __post_init__(self) -> None:
        if not isinstance(self.crs, str) or not self.crs.strip():
            raise SpatialGridInputError("crs must identify a WGS84 / UTM South CRS.")
        size = _finite_number(self.cell_size_meters, "cell_size_meters")
        if size <= 0:
            raise SpatialGridInputError("cell_size_meters must be positive.")
        projection = _projection(self.crs)
        object.__setattr__(self, "crs", f"EPSG:{projection.crs.to_epsg()}")
        object.__setattr__(self, "cell_size_meters", size)


@dataclass(frozen=True, slots=True)
class SpatialCell:
    cell_id: str
    crs: str
    cell_size_meters: float
    grid_x: int
    grid_y: int
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    center_latitude: float
    center_longitude: float


def _axis_bounds(coordinate: float, size: float) -> tuple[int, float, float]:
    """Use floor (including negatives) relative to the immutable origin zero."""
    quotient = coordinate / size
    if not isfinite(quotient):
        raise SpatialGridInputError("Cell size is too small for projected coordinate precision.")
    index = floor(quotient)
    try:
        lower = index * size
        upper = (index + 1) * size
    except OverflowError as exc:
        raise SpatialGridInputError("Cell bounds exceed supported numeric precision.") from exc
    if not (
        isfinite(lower) and isfinite(upper)
        and lower < lower + (upper - lower) / 2 < upper
        and lower <= coordinate < upper
    ):
        raise SpatialGridInputError("Cell bounds cannot be represented at this resolution.")
    return index, lower, upper


def get_spatial_cell(
    *, latitude: float, longitude: float, config: SpatialGridConfig
) -> SpatialCell:
    """Assign one WGS84 coordinate without auto-switching projection or origin.

    The configured CRS's geographic area of use is checked inclusively. Cell
    bounds are half-open; no epsilon snapping is applied to projected points.
    IDs encode version, canonical CRS, exact float size and integer indices.
    """
    x, y, grid_x, x_min, x_max, grid_y, y_min, y_max = _project_grid_coordinates(
        latitude=latitude, longitude=longitude, config=config,
    )
    projection = _projection(config.crs)
    try:
        center_lon, center_lat = projection.inverse.transform(
            x_min + (x_max - x_min) / 2,
            y_min + (y_max - y_min) / 2,
            errcheck=True,
        )
    except ProjError as exc:
        raise SpatialGridInputError("Coordinate transformation failed.") from exc
    return _build_cell(config, grid_x, grid_y, x_min, x_max, y_min, y_max, center_lon, center_lat)


def _project_grid_coordinates(
    *, latitude: float, longitude: float, config: SpatialGridConfig,
) -> tuple[float, float, int, float, float, int, float, float]:
    """Validate and project once; return both grid bounds and projected point."""
    if not isinstance(config, SpatialGridConfig):
        raise SpatialGridInputError("config must be a SpatialGridConfig value.")
    lat = _finite_number(latitude, "latitude")
    lon = _finite_number(longitude, "longitude")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise SpatialGridInputError("Latitude or longitude is outside its geographic range.")
    projection = _projection(config.crs)
    area = projection.crs.area_of_use
    if not (area.west <= lon <= area.east and area.south <= lat <= area.north):
        raise SpatialGridInputError("Coordinate is outside the configured CRS area of use.")
    try:
        x, y = projection.forward.transform(lon, lat, errcheck=True)
        if not isfinite(x) or not isfinite(y):
            raise SpatialGridInputError("Projection returned non-finite coordinates.")
        grid_x, x_min, x_max = _axis_bounds(x, config.cell_size_meters)
        grid_y, y_min, y_max = _axis_bounds(y, config.cell_size_meters)
    except ProjError as exc:
        raise SpatialGridInputError("Coordinate transformation failed.") from exc
    return x, y, grid_x, x_min, x_max, grid_y, y_min, y_max


def _build_cell(
    config: SpatialGridConfig, grid_x: int, grid_y: int,
    x_min: float, x_max: float, y_min: float, y_max: float,
    center_lon: float, center_lat: float,
) -> SpatialCell:
    if not (
        isfinite(center_lat) and isfinite(center_lon)
        and -90 <= center_lat <= 90 and -180 <= center_lon <= 180
    ):
        raise SpatialGridInputError("Inverse projection returned an invalid geographic center.")
    return SpatialCell(
        cell_id=f"manea-grid:v1:{config.crs}:{config.cell_size_meters!r}:{grid_x}:{grid_y}",
        crs=config.crs,
        cell_size_meters=config.cell_size_meters,
        grid_x=grid_x,
        grid_y=grid_y,
        x_min=x_min,
        y_min=y_min,
        x_max=x_max,
        y_max=y_max,
        center_latitude=center_lat,
        center_longitude=center_lon,
    )


@lru_cache(maxsize=4096)
def _cached_cell_geometry(crs: str, size: float, grid_x: int, grid_y: int) -> SpatialCell:
    """Internal bounded reuse of immutable geometry, including inverse projection."""
    config = SpatialGridConfig(crs=crs, cell_size_meters=size)
    x_min, x_max = grid_x * size, (grid_x + 1) * size
    y_min, y_max = grid_y * size, (grid_y + 1) * size
    try:
        center_lon, center_lat = _projection(crs).inverse.transform(
            x_min + (x_max - x_min) / 2, y_min + (y_max - y_min) / 2,
            errcheck=True,
        )
    except ProjError as exc:
        raise SpatialGridInputError("Coordinate transformation failed.") from exc
    return _build_cell(config, grid_x, grid_y, x_min, x_max, y_min, y_max, center_lon, center_lat)


def _project_cached_cell(
    *, latitude: float, longitude: float, config: SpatialGridConfig,
) -> tuple[SpatialCell, float, float]:
    """Internal aggregation path: one forward transform and cached cell center."""
    x, y, grid_x, _x_min, _x_max, grid_y, _y_min, _y_max = _project_grid_coordinates(
        latitude=latitude, longitude=longitude, config=config,
    )
    return _cached_cell_geometry(config.crs, config.cell_size_meters, grid_x, grid_y), x, y
