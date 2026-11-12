import asyncio
from datetime import datetime, timedelta
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.analytics.spatial_grid import SpatialGridConfig, get_spatial_cell
from src.db.config.connection import get_db
from src.routers.heatmap import router
from src.schemas.heatmap import HeatmapRequest, HeatmapSubjectType
from src.schemas.user import TokenData
from src.service.heatmap_service import HeatmapService
from src.service.historical_spatial_analytics_service import HistoricalAnalyticsLimitExceeded
from src.service.crud_user import get_current_user


START = datetime(2026, 1, 1)
GRID = SpatialGridConfig("EPSG:32720", 25)


def _run_async(test_function):
    @wraps(test_function)
    def wrapper(*args, **kwargs):
        asyncio.run(test_function(*args, **kwargs))
    return wrapper


def analytics_result(*, entries=(), raw_count=2):
    return SimpleNamespace(
        buckets=tuple(
            SimpleNamespace(
                spatial_cell_id=cell.cell_id,
                cell=cell,
                dwell_seconds=seconds,
            )
            for cell, seconds in entries
        ),
        metadata=SimpleNamespace(
            raw_location_count=raw_count,
            dwell_seconds=sum(seconds for _, seconds in entries),
            temporal_coverage_ratio=0.75,
            observed_seconds=450,
            eligible_assignment_seconds=600,
            requested_seconds=600,
            crs=GRID.crs,
            spatial_cell_size_meters=GRID.cell_size_meters,
        ),
    )


@_run_async
async def test_heatmap_aggregates_same_cell_and_preserves_dwell_and_polygon_coordinates():
    first = get_spatial_cell(latitude=-33.651, longitude=-65.472, config=GRID)
    second = get_spatial_cell(latitude=-33.651, longitude=-65.471, config=GRID)
    analytics = SimpleNamespace(
        analyze_asset=AsyncMock(return_value=analytics_result(entries=((first, 20), (first, 30), (second, 10)))),
        analyze_asset_group=AsyncMock(),
    )
    request = HeatmapRequest(
        subject_type="asset", subject_id=8, window_start=START,
        window_end=START + timedelta(seconds=600),
    )
    with patch("src.service.heatmap_service.HistoricalSpatialAnalyticsService", return_value=analytics):
        response = await HeatmapService(None).query(client_id=17, request=request)

    assert response.availability == "available"
    assert response.total_dwell_seconds == 60
    assert [(cell.spatial_cell_id, cell.dwell_seconds) for cell in response.cells] == [
        (first.cell_id, 50), (second.cell_id, 10),
    ]
    polygon = response.cells[0].geometry
    assert polygon.type == "Polygon"
    ring = polygon.coordinates[0]
    assert len(ring) == 5
    assert ring[0] == ring[-1]
    assert all(-180 <= coordinate[0] <= 180 and -90 <= coordinate[1] <= 90 for coordinate in ring)
    assert response.model_dump(mode="json")["cells"][0]["geometry"]["type"] == "Polygon"
    analytics.analyze_asset.assert_awaited_once()
    assert analytics.analyze_asset.await_args.kwargs["client_id"] == 17


@_run_async
async def test_heatmap_selects_individual_or_group_engine_method():
    cell = get_spatial_cell(latitude=-33.651, longitude=-65.472, config=GRID)
    analytics = SimpleNamespace(
        analyze_asset=AsyncMock(return_value=analytics_result(entries=((cell, 125),))),
        analyze_asset_group=AsyncMock(return_value=analytics_result(entries=((cell, 125),))),
    )
    with patch("src.service.heatmap_service.HistoricalSpatialAnalyticsService", return_value=analytics):
        for subject_type, method_name, id_name in (
            (HeatmapSubjectType.ASSET, "analyze_asset", "asset_id"),
            (HeatmapSubjectType.ASSET_GROUP, "analyze_asset_group", "group_id"),
        ):
            request = HeatmapRequest(
                subject_type=subject_type, subject_id=12,
                window_start=START, window_end=START + timedelta(hours=1),
            )
            response = await HeatmapService(None).query(client_id=17, request=request)
            assert getattr(analytics, method_name).await_args.kwargs[id_name] == 12
            assert response.cells[0].dwell_seconds == 125
    analytics.analyze_asset.assert_awaited_once()
    analytics.analyze_asset_group.assert_awaited_once()


@_run_async
async def test_empty_heatmap_distinguishes_no_data_from_insufficient_evidence():
    for raw_count, expected in ((0, "no_data"), (3, "insufficient_evidence")):
        analytics = SimpleNamespace(
            analyze_asset=AsyncMock(return_value=analytics_result(raw_count=raw_count)),
            analyze_asset_group=AsyncMock(),
        )
        request = HeatmapRequest(
            subject_type="asset", subject_id=8, window_start=START,
            window_end=START + timedelta(seconds=600),
        )
        with patch("src.service.heatmap_service.HistoricalSpatialAnalyticsService", return_value=analytics):
            response = await HeatmapService(None).query(client_id=17, request=request)
        assert response.availability == expected
        assert response.cells == []


@_run_async
async def test_heatmap_rejects_window_over_limit_before_engine_call():
    try:
        await HeatmapService(None).query(
            client_id=17,
            request=HeatmapRequest(
                subject_type="asset", subject_id=8, window_start=START,
                window_end=START + timedelta(days=8),
            ),
        )
    except HistoricalAnalyticsLimitExceeded:
        return
    raise AssertionError("Expected over-limit window to be rejected")


def _app(*, client_id=17):
    app = FastAPI()
    app.include_router(router)

    async def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        user_id=1, username="user", client_id=client_id,
    )
    return app


def test_heatmap_route_uses_client_from_authenticated_user():
    response_data = {
        "subject_type": "asset",
        "subject_id": 8,
        "window_start": START.isoformat(),
        "window_end": (START + timedelta(seconds=600)).isoformat(),
        "availability": "no_data",
        "total_dwell_seconds": 0,
        "coverage": {
            "temporal_coverage_ratio": None,
            "observed_seconds": 0,
            "eligible_assignment_seconds": 0,
            "requested_seconds": 600,
        },
        "crs": "EPSG:32720",
        "cell_size_meters": 25,
        "cells": [],
    }
    service = SimpleNamespace(query=AsyncMock(return_value=response_data))
    permission_check = AsyncMock(return_value=True)
    with patch("src.routers.heatmap.HeatmapService", return_value=service), \
            patch("src.routers.heatmap.validate_user_service_access", permission_check):
        response = TestClient(_app()).post("/analytics/heatmaps", json={
            "subject_type": "asset", "subject_id": 8,
            "window_start": START.isoformat(),
            "window_end": (START + timedelta(seconds=600)).isoformat(),
        })

    assert response.status_code == 200
    assert service.query.await_args.kwargs["client_id"] == 17
    permission_check.assert_awaited_once()
    assert permission_check.await_args.args[1] == "asset:get my assets"


def test_heatmap_route_requires_a_client_scope():
    response = TestClient(_app(client_id=None)).post("/analytics/heatmaps", json={
        "subject_type": "asset", "subject_id": 8,
        "window_start": START.isoformat(),
        "window_end": (START + timedelta(seconds=600)).isoformat(),
    })
    assert response.status_code == 400
