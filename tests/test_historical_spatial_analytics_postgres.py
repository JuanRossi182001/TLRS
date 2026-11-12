"""Opt-in disposable PostGIS checks; never run against a non-test database."""

from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text, func
from pyproj import Transformer

from src.application.analytics.spatial_grid import SpatialGridConfig, get_spatial_cell
from src.application.analytics.performance_profile import ProcessingProfile
from src.application.analytics.observation_attribution import (
    TemporalObservationRef, attribute_observed_time_to_observations,
)
from src.application.analytics.observation_bucketing import bucket_observation_contributions
from src.application.analytics.observed_time import calculate_observed_time
from src.application.analytics.spatial_assessment import (
    SpatialObservationRef, assess_spatial_interval,
)
from src.application.analytics.spatial_qualification import qualify_observed_time
from src.application.analytics.spatial_aggregation import aggregate_spatial_time
from src.application.analytics.temporal_continuity import analyze_temporal_continuity
from src.schemas.heatmap import HeatmapRequest
from src.models.asset import Asset, AssetStatus
from src.models.client import Client
from src.models.device import Device, DeviceState, DeviceCommunicationProtocol
from src.models.device_asset_assignment import DeviceAssetAssignment
from src.models.location import Location
from src.service.historical_spatial_analytics_repository import HistoricalSpatialAnalyticsRepository
from src.service.historical_spatial_analytics_service import (
    HistoricalSpatialAnalyticsService, HistoricalAnalyticsNotFound, HistoricalAnalyticsLimits,
)
from src.service.heatmap_service import HeatmapService


pytestmark = [pytest.mark.integration, pytest.mark.anyio]
START = datetime(2026, 9, 1, 12)
GRID = SpatialGridConfig("EPSG:32720", 25)


async def test_postgis_projection_and_analytics_index(test_session_factory):
    async with test_session_factory() as session:
        row = await session.execute(text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'locations' AND column_name = 'device_timestamp'
        """))
        assert row.scalar_one() == "timestamp without time zone"
        row = await session.execute(text("""
            SELECT indexdef FROM pg_indexes WHERE tablename='locations'
            AND indexname='ix_locations_analytics_device_observed'
        """))
        definition = row.scalar_one().lower()
        assert "coalesce" in definition and "deleted" in definition
        transform = Transformer.from_crs(4326, GRID.crs, always_xy=True)
        inverse = Transformer.from_crs(GRID.crs, 4326, always_xy=True)
        known = get_spatial_cell(latitude=-33.651, longitude=-65.472, config=GRID)
        points = [(-65.472, -33.651)]
        for offset in (-0.01, 0.01):
            points.append(inverse.transform(known.x_max + offset, (known.y_min + known.y_max) / 2))
        for lon, lat in points:
            sql = await session.execute(text("""
                SELECT ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), CAST(:srid AS integer))),
                       ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), CAST(:srid AS integer)))
            """), {"lon": lon, "lat": lat, "srid": 32720})
            x, y = sql.one()
            python_cell = get_spatial_cell(latitude=lat, longitude=lon, config=GRID)
            assert (int(x // 25), int(y // 25)) == (python_cell.grid_x, python_cell.grid_y)
            px, py = transform.transform(lon, lat)
            assert abs(x - px) < 0.001 and abs(y - py) < 0.001


async def test_real_location_history_scope_reassignment_and_no_fix(test_session_factory):
    async with test_session_factory() as session:
        await session.begin()
        try:
            suffix = uuid4().hex
            client = Client(name="Analytics test", email=f"analytics-{suffix}@example.test")
            other_client = Client(name="Other analytics", email=f"other-analytics-{suffix}@example.test")
            session.add_all((client, other_client))
            await session.flush()
            first = Asset(asset_type="CATTLE", serial=f"ANALYTICS-A-{suffix}",
                          client_id=client.id_client, status=AssetStatus.ACTIVE)
            second = Asset(asset_type="CATTLE", serial=f"ANALYTICS-B-{suffix}",
                           client_id=client.id_client, status=AssetStatus.ACTIVE)
            foreign = Asset(asset_type="CATTLE", serial=f"ANALYTICS-X-{suffix}",
                            client_id=other_client.id_client, status=AssetStatus.ACTIVE)
            session.add_all((first, second, foreign))
            await session.flush()
            device = Device(serial=f"ANALYTICS-DEVICE-{suffix}", name="Analytics collar",
                            type="COLLAR", client_id=client.id_client,
                            asset_id=second.id_asset, active=True, state=DeviceState.OFF,
                            communication_protocol=DeviceCommunicationProtocol.MQTT)
            session.add(device)
            await session.flush()
            session.add_all((
                DeviceAssetAssignment(device_id=device.id_device, asset_id=first.id_asset,
                                      assigned_at=START, unassigned_at=START + timedelta(minutes=3)),
                DeviceAssetAssignment(device_id=device.id_device, asset_id=second.id_asset,
                                      assigned_at=START + timedelta(minutes=3),
                                      unassigned_at=START + timedelta(minutes=6)),
            ))
            for i in range(10):
                time = START + timedelta(seconds=i * 15)
                session.add(Location(device_id=device.id_device, device_timestamp=time,
                                     received_at=time + timedelta(seconds=1), latitude=-33.651,
                                     longitude=-65.472, accuracy=255 if i == 5 else 1, deleted="N"))
            for i in range(10):
                time = START + timedelta(minutes=3, seconds=i * 15)
                session.add(Location(device_id=device.id_device, device_timestamp=time,
                                     received_at=time + timedelta(seconds=1), latitude=-33.651,
                                     longitude=-65.472, accuracy=1, deleted="N"))
            await session.flush()
            await session.execute(text("ANALYZE locations"))
            explain = text("""
                EXPLAIN (ANALYZE, BUFFERS)
                SELECT id_location, COALESCE(device_timestamp, received_at) AS observed_at
                FROM locations
                WHERE device_id = :device_id AND deleted = 'N'
                  AND COALESCE(device_timestamp, received_at) >= :start
                  AND COALESCE(device_timestamp, received_at) < :end
                ORDER BY COALESCE(device_timestamp, received_at), id_location LIMIT 500
            """)
            params = {"device_id": device.id_device, "start": START,
                      "end": START + timedelta(minutes=6)}
            plan = "\n".join(row[0] for row in (await session.execute(explain, params)).all())
            assert "Buffers:" in plan and "actual time=" in plan
            print("analytics_fixture_explain:\n" + plan)
            await session.execute(text("SET LOCAL enable_seqscan = off"))
            index_plan = "\n".join(row[0] for row in (await session.execute(explain, params)).all())
            assert "ix_locations_analytics_device_observed" in index_plan
            await session.execute(text("SET LOCAL enable_seqscan = on"))
            profile = ProcessingProfile()
            repository = HistoricalSpatialAnalyticsRepository(session)
            service = HistoricalSpatialAnalyticsService(session, repository=repository, profile=profile)
            result = await service.analyze_assets(
                client_id=client.id_client, asset_ids=(first.id_asset, second.id_asset),
                window_start=START, window_end=START + timedelta(minutes=6), grid_config=GRID,
            )
            assert result.metadata.observed_seconds == 270
            assert result.metadata.spatially_uncertain_seconds == 30
            assert result.metadata.dwell_seconds == 240
            assert result.metadata.eligible_assignment_seconds == 360
            assert result.metadata.raw_location_count == 20
            assert profile.sql_query_count >= 7
            assert profile.rows_fetched >= 20
            assert profile.location_page_count >= 2
            assert profile.neighbor_query_count == 4
            assert profile.locations_processed == result.metadata.processed_location_count
            assert profile.total_seconds >= profile.sql_execute_seconds
            assert {b.asset_id for b in result.buckets} == {first.id_asset, second.id_asset}
            by_asset = {asset_id: sum(b.dwell_seconds for b in result.buckets if b.asset_id == asset_id)
                        for asset_id in (first.id_asset, second.id_asset)}
            assert by_asset == {first.id_asset: 105, second.id_asset: 135}
            for size in (1, 2, 7, 500):
                paged = await service.analyze_assets(
                    client_id=client.id_client, asset_ids=(first.id_asset, second.id_asset),
                    window_start=START, window_end=START + timedelta(minutes=6),
                    grid_config=GRID, limits=HistoricalAnalyticsLimits(page_size=size),
                )
                assert paged == result
            # Independent, unbatched Python reference against the actual SQL rows.
            expected_buckets = []
            reference_observed = 0.0
            for asset_id, lower, upper in (
                (first.id_asset, START, START + timedelta(minutes=3)),
                (second.id_asset, START + timedelta(minutes=3), START + timedelta(minutes=6)),
            ):
                rows = (await session.execute(
                    select(Location.id_location, func.coalesce(Location.device_timestamp, Location.received_at),
                           Location.latitude, Location.longitude, Location.accuracy)
                    .where(Location.device_id == device.id_device,
                           func.coalesce(Location.device_timestamp, Location.received_at) >= lower,
                           func.coalesce(Location.device_timestamp, Location.received_at) < upper)
                    .order_by(func.coalesce(Location.device_timestamp, Location.received_at), Location.id_location)
                )).all()
                refs = tuple(SpatialObservationRef(*row) for row in rows)
                continuity = analyze_temporal_continuity([ref.observed_at for ref in refs])
                observed = calculate_observed_time(continuity)
                reference_observed += observed.metadata.observed_seconds
                attributed = attribute_observed_time_to_observations(
                    tuple(TemporalObservationRef(ref.observation_id, ref.observed_at) for ref in refs), continuity,
                )
                bucketed = bucket_observation_contributions(
                    contributions=attributed.contributions, window_start=START,
                    window_end=START + timedelta(minutes=6), bucket_seconds=result.metadata.bucket_seconds,
                )
                spatial = tuple(assess_spatial_interval(left, right, assessment)
                                for left, right, assessment in zip(refs, refs[1:], continuity))
                qualified = qualify_observed_time(
                    contributions=bucketed.contributions, temporal=continuity, spatial=spatial,
                    window_start=START, window_end=START + timedelta(minutes=6),
                )
                aggregated = aggregate_spatial_time(
                    asset_id=asset_id, qualified=qualified,
                    observations={ref.observation_id: ref for ref in refs}, config=GRID,
                )
                expected_buckets.extend(aggregated.buckets)
            assert reference_observed == result.metadata.observed_seconds
            assert sorted((b.asset_id, b.bucket_start, b.spatial_cell_id, b.dwell_seconds)
                          for b in expected_buckets) == sorted(
                (b.asset_id, b.bucket_start, b.spatial_cell_id, b.dwell_seconds)
                for b in result.buckets
            )
            with pytest.raises(HistoricalAnalyticsNotFound):
                await service.analyze_asset(client_id=client.id_client, asset_id=foreign.id_asset,
                                            window_start=START, window_end=START + timedelta(minutes=6),
                                            grid_config=GRID)
            result = await service.analyze_asset(
                client_id=client.id_client, asset_id=first.id_asset,
                window_start=START + timedelta(seconds=7),
                window_end=START + timedelta(seconds=100), grid_config=GRID,
            )
            assert result.metadata.observed_seconds == 93
            assert result.metadata.dwell_seconds <= 93
            assert result.metadata.temporal_coverage_ratio == 1
        finally:
            await session.rollback()


async def test_fresh_service_enforces_read_only_snapshot(test_session_factory):
    async with test_session_factory() as session:
        service = HistoricalSpatialAnalyticsService(session)
        with pytest.raises(HistoricalAnalyticsNotFound):
            await service.analyze_asset(
                client_id=999999, asset_id=999999, window_start=START,
                window_end=START + timedelta(minutes=5), grid_config=GRID,
            )
        assert not session.in_transaction()


async def test_pages_preserve_irregular_cadence_duplicate_gap_and_clipping(test_session_factory):
    async with test_session_factory() as session:
        await session.begin()
        try:
            suffix = uuid4().hex
            client = Client(name="Page boundary", email=f"page-{suffix}@example.test")
            session.add(client)
            await session.flush()
            asset = Asset(asset_type="CATTLE", serial=f"PAGE-{suffix}",
                          client_id=client.id_client, status=AssetStatus.ACTIVE)
            session.add(asset)
            await session.flush()
            device = Device(serial=f"PAGE-DEVICE-{suffix}", name="Page collar",
                            type="COLLAR", client_id=client.id_client, asset_id=asset.id_asset,
                            active=True, state=DeviceState.OFF,
                            communication_protocol=DeviceCommunicationProtocol.MQTT)
            session.add(device)
            await session.flush()
            deltas = [60] * 4 + [0] + [60] * 4 + [3600] + [60] * 4 + [5] * 4 + [600] * 5
            moments = [START]
            for delta in deltas:
                moments.append(moments[-1] + timedelta(seconds=delta))
            session.add(DeviceAssetAssignment(
                device_id=device.id_device, asset_id=asset.id_asset,
                assigned_at=START, unassigned_at=moments[-1] + timedelta(seconds=1),
            ))
            for time in moments:
                session.add(Location(device_id=device.id_device, device_timestamp=time,
                                     received_at=time + timedelta(seconds=2), latitude=-33.651,
                                     longitude=-65.472, accuracy=1, deleted="N"))
            await session.flush()
            reference = None
            for size in (500, 7, 2, 1):
                result = await HistoricalSpatialAnalyticsService(
                    session, repository=HistoricalSpatialAnalyticsRepository(session)
                ).analyze_asset(
                    client_id=client.id_client, asset_id=asset.id_asset,
                    window_start=START + timedelta(seconds=30),
                    window_end=moments[-1] - timedelta(seconds=30),
                    grid_config=GRID, limits=HistoricalAnalyticsLimits(page_size=size),
                )
                if reference is None:
                    reference = result
                    assert result.metadata.raw_location_count > 15
                    assert result.metadata.gap_seconds > 0
                else:
                    assert result == reference
        finally:
            await session.rollback()


async def test_postgres_heatmap_spatial_evidence_accepts_stable_600_second_reports(test_session_factory):
    async with test_session_factory() as session:
        await session.begin()
        try:
            suffix = uuid4().hex
            client = Client(name="600 second heatmap", email=f"heatmap-{suffix}@example.test")
            session.add(client)
            await session.flush()
            asset = Asset(asset_type="CATTLE", serial=f"HEATMAP-{suffix}",
                          client_id=client.id_client, status=AssetStatus.ACTIVE)
            session.add(asset)
            await session.flush()
            device = Device(serial=f"HEATMAP-DEVICE-{suffix}", name="Heatmap collar",
                            type="COLLAR", client_id=client.id_client, asset_id=asset.id_asset,
                            active=True, state=DeviceState.OFF,
                            communication_protocol=DeviceCommunicationProtocol.MQTT)
            session.add(device)
            await session.flush()
            window_start = START
            window_end = START + timedelta(seconds=6000)
            session.add(DeviceAssetAssignment(
                device_id=device.id_device, asset_id=asset.id_asset,
                assigned_at=window_start - timedelta(seconds=600),
                unassigned_at=window_end + timedelta(seconds=600),
            ))
            for index in range(13):
                moment = window_start - timedelta(seconds=600) + timedelta(seconds=600 * index)
                session.add(Location(
                    device_id=device.id_device, device_timestamp=moment,
                    received_at=moment + timedelta(seconds=2), latitude=-33.651,
                    longitude=-65.472, accuracy=1, deleted="N",
                ))
            await session.flush()

            request = HeatmapRequest(
                subject_type="asset", subject_id=asset.id_asset,
                window_start=window_start, window_end=window_end,
            )
            with patch(
                "src.service.heatmap_service.HistoricalSpatialAnalyticsService",
                side_effect=lambda db: HistoricalSpatialAnalyticsService(
                    db, repository=HistoricalSpatialAnalyticsRepository(db),
                ),
            ):
                result = await HeatmapService(session).query(client_id=client.id_client, request=request)

            assert result.availability == "available"
            assert result.coverage.observed_seconds == 6000
            assert result.total_dwell_seconds == 6000
            assert sum(cell.dwell_seconds for cell in result.cells) == 6000
            assert len(result.cells) == 1
            ring = result.cells[0].geometry.coordinates[0]
            assert len(ring) == 5 and ring[0] == ring[-1]
            assert all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in ring)
        finally:
            await session.rollback()
