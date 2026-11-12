"""Application service for bounded heatmap queries over historical dwell."""

from datetime import datetime, timedelta
from functools import lru_cache

from pyproj import Transformer

from src.application.analytics.spatial_assessment import SpatialAssessmentConfig
from src.application.analytics.spatial_grid import SpatialGridConfig
from src.schemas.heatmap import (
    HeatmapCell,
    HeatmapCoverage,
    HeatmapPolygon,
    HeatmapRequest,
    HeatmapResponse,
    HeatmapSubjectType,
)
from src.service.historical_spatial_analytics_service import (
    HistoricalAnalyticsLimitExceeded,
    HistoricalAnalyticsLimits,
    HistoricalSpatialAnalyticsService,
)


MAX_HEATMAP_WINDOW = timedelta(days=7)
HEATMAP_LIMITS = HistoricalAnalyticsLimits(
    max_assets=20,
    max_assignments=100,
    max_locations=150_000,
    max_fragments=300_000,
    max_cells=10_000,
    max_results=15_000,
    page_size=500,
    max_query_seconds=20,
)
HEATMAP_GRID = SpatialGridConfig("EPSG:32720", 25)
# This tolerance is scoped to heatmaps. Geofence and other spatial consumers
# retain the default 60 second evidence interval.
HEATMAP_ASSESSMENT = SpatialAssessmentConfig(
    max_stationary_evidence_interval_seconds=600,
)


@lru_cache(maxsize=8)
def _inverse_transformer(crs: str) -> Transformer:
    return Transformer.from_crs(crs, "EPSG:4326", always_xy=True, allow_ballpark=False, only_best=True)


def _cell_polygon(cell) -> HeatmapPolygon:
    transformer = _inverse_transformer(cell.crs)
    projected_ring = (
        (cell.x_min, cell.y_min),
        (cell.x_max, cell.y_min),
        (cell.x_max, cell.y_max),
        (cell.x_min, cell.y_max),
        (cell.x_min, cell.y_min),
    )
    coordinates = [
        [list(transformer.transform(x, y, errcheck=True)) for x, y in projected_ring]
    ]
    return HeatmapPolygon(coordinates=coordinates)


class HeatmapService:
    def __init__(self, db):
        self.db = db

    async def query(self, *, client_id: int, request: HeatmapRequest) -> HeatmapResponse:
        start = request.window_start
        end = request.window_end
        if end <= start:
            raise ValueError("window_end must be later than window_start")
        if end - start > MAX_HEATMAP_WINDOW:
            raise HistoricalAnalyticsLimitExceeded("Heatmap window exceeds the 7 day limit.")

        analytics = HistoricalSpatialAnalyticsService(self.db)
        arguments = {
            "client_id": client_id,
            "window_start": start,
            "window_end": end,
            "grid_config": HEATMAP_GRID,
            "assessment_config": HEATMAP_ASSESSMENT,
            "limits": HEATMAP_LIMITS,
        }
        if request.subject_type == HeatmapSubjectType.ASSET:
            result = await analytics.analyze_asset(asset_id=request.subject_id, **arguments)
        else:
            result = await analytics.analyze_asset_group(group_id=request.subject_id, **arguments)

        cells_by_id = {}
        for bucket in result.buckets:
            existing = cells_by_id.get(bucket.spatial_cell_id)
            if existing is None:
                cells_by_id[bucket.spatial_cell_id] = [bucket.cell, bucket.dwell_seconds]
            else:
                existing[1] += bucket.dwell_seconds

        cells = [
            HeatmapCell(
                spatial_cell_id=cell_id,
                geometry=_cell_polygon(cell),
                dwell_seconds=seconds,
            )
            for cell_id, (cell, seconds) in sorted(cells_by_id.items())
        ]
        metadata = result.metadata
        availability = (
            "available" if cells
            else "insufficient_evidence" if metadata.raw_location_count > 0
            else "no_data"
        )
        return HeatmapResponse(
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            window_start=start,
            window_end=end,
            availability=availability,
            total_dwell_seconds=metadata.dwell_seconds,
            coverage=HeatmapCoverage(
                temporal_coverage_ratio=metadata.temporal_coverage_ratio,
                observed_seconds=metadata.observed_seconds,
                eligible_assignment_seconds=metadata.eligible_assignment_seconds,
                requested_seconds=metadata.requested_seconds,
            ),
            crs=metadata.crs,
            cell_size_meters=metadata.spatial_cell_size_meters,
            cells=cells,
        )
