"""Opt-in load profile for the write-capable geofence ingestion path.

Run only through scripts/run-integration-tests.sh, which uses and removes the
local disposable PostGIS database.
"""

import asyncio
import math
import statistics
from datetime import datetime
from time import perf_counter
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.application.telemetry.normalized_telemetry import NormalizedTelemetry
from src.models.asset import Asset, AssetStatus
from src.models.client import Client
from src.models.device import Device, DeviceCommunicationProtocol, DeviceState
from src.models.geofence import (
    GeoFence,
    GeoFenceAssetState,
    GeoFenceAssignment,
    GeoFenceEvent,
)
from src.service.location_ingestion_service import LocationIngestionService


pytestmark = [pytest.mark.integration, pytest.mark.anyio]
DEVICE_COUNT = 30
FENCES_PER_ASSET = 5
MESSAGES_PER_STAGE = 30
CONCURRENCY_LEVELS = (1, 5, 10)
LATITUDE = -33.25
LONGITUDE = -65.25
FENCE_SHAPE = WKTElement(
    "MULTIPOLYGON(((-65.5 -33.5, -65.0 -33.5, -65.0 -33.0, "
    "-65.5 -33.0, -65.5 -33.5)))",
    srid=4326,
)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


async def test_geofence_ingestion_load_profile(test_session_factory) -> None:
    suffix = uuid4().hex
    test_engine = test_session_factory.kw["bind"]
    engine = create_async_engine(
        test_engine.url,
        pool_size=10,
        max_overflow=5,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            client = Client(
                name=f"Geofence load {suffix}",
                email=f"geofence-load-{suffix}@example.test",
            )
            session.add(client)
            await session.flush()
            device_ids: list[int] = []
            for device_number in range(DEVICE_COUNT):
                asset = Asset(
                    asset_type="LOAD_TEST",
                    serial=f"LOAD-ASSET-{suffix}-{device_number}",
                    client_id=client.id_client,
                    status=AssetStatus.ACTIVE,
                )
                session.add(asset)
                await session.flush()
                device = Device(
                    serial=f"LOAD-DEVICE-{suffix}-{device_number}",
                    name=f"Load device {device_number}",
                    type="LOAD_TEST",
                    client_id=client.id_client,
                    asset_id=asset.id_asset,
                    active=True,
                    state=DeviceState.ON,
                    communication_protocol=DeviceCommunicationProtocol.HTTP,
                )
                session.add(device)
                await session.flush()
                device_ids.append(device.id_device)

                for fence_number in range(FENCES_PER_ASSET):
                    fence = GeoFence(
                        client_id=client.id_client,
                        name=f"Load fence {device_number}-{fence_number}",
                        shape=FENCE_SHAPE,
                        active=True,
                    )
                    session.add(fence)
                    await session.flush()
                    session.add(
                        GeoFenceAssignment(
                            fence_id=fence.id_geofence,
                            asset_id=asset.id_asset,
                            active=True,
                        )
                    )
            await session.commit()

        async def process_location(
            device_id: int,
            *,
            latitude: float = LATITUDE,
            longitude: float = LONGITUDE,
        ) -> tuple[float, int, int]:
            async with session_factory() as session:
                device = await session.scalar(
                    select(Device).where(Device.id_device == device_id)
                )
                assert device is not None
                telemetry = NormalizedTelemetry(
                    device_timestamp=None,
                    latitude=latitude,
                    longitude=longitude,
                    altitude=520.0,
                    accuracy=3.0,
                )
                started = perf_counter()
                _, results = await LocationIngestionService(
                    session
                ).persist_location_with_statuses(
                    device=device,
                    normalized_telemetry=telemetry,
                    received_at=datetime.utcnow(),
                )
                await session.commit()
                elapsed_ms = (perf_counter() - started) * 1000
                return (
                    elapsed_ms,
                    len(results),
                    sum(result.event_created for result in results),
                )

        async def run_batch(
            concurrency: int,
        ) -> tuple[list[tuple[float, int, int]], float]:
            semaphore = asyncio.Semaphore(concurrency)

            async def limited(device_id: int):
                async with semaphore:
                    return await process_location(device_id)

            started = perf_counter()
            results = await asyncio.gather(
                *(limited(device_id) for device_id in device_ids)
            )
            return results, perf_counter() - started

        # Warm the worker, connection pool, and stable SAFE state before measuring.
        warmup, _ = await run_batch(concurrency=5)
        assert all(fence_count == FENCES_PER_ASSET for _, fence_count, _ in warmup)
        assert all(event_count == 0 for _, _, event_count in warmup)

        for concurrency in CONCURRENCY_LEVELS:
            batch, wall_seconds = await run_batch(concurrency)
            latencies = [elapsed for elapsed, _, _ in batch]
            assert len(batch) == MESSAGES_PER_STAGE
            assert all(fence_count == FENCES_PER_ASSET for _, fence_count, _ in batch)
            assert all(event_count == 0 for _, _, event_count in batch)
            throughput = len(batch) / wall_seconds if wall_seconds else 0
            print(
                "geofence_load "
                f"concurrency={concurrency} messages={len(batch)} "
                f"p50_ms={statistics.median(latencies):.2f} "
                f"p95_ms={_percentile(latencies, 0.95):.2f} "
                f"max_ms={max(latencies):.2f} "
                f"throughput_msg_s={throughput:.2f}"
            )

        # Verify transition/event behavior separately from the no-transition
        # throughput profile; command dispatch is intentionally not part of
        # this geofence evaluation benchmark.
        outside_latitude = LATITUDE
        outside_longitude = -65.75
        with patch(
            "src.service.geofence_evaluation_service.DeviceCommandService."
            "create_commands_for_geofence_event",
            new=AsyncMock(return_value=[]),
        ):
            _, fence_count, event_count = await process_location(
                device_ids[0],
                latitude=outside_latitude,
                longitude=outside_longitude,
            )
        assert fence_count == FENCES_PER_ASSET
        assert event_count == FENCES_PER_ASSET

        async with session_factory() as session:
            persisted_events = await session.scalar(
                select(func.count(GeoFenceEvent.id_event)).where(
                    GeoFenceEvent.device_id == device_ids[0]
                )
            )
        assert persisted_events == FENCES_PER_ASSET

        # Two concurrent evaluations for the same asset must serialize on
        # locked state rows and emit only one EXITED event per fence.
        with patch(
            "src.service.geofence_evaluation_service.DeviceCommandService."
            "create_commands_for_geofence_event",
            new=AsyncMock(return_value=[]),
        ):
            concurrent_results = await asyncio.gather(
                process_location(
                    device_ids[1],
                    latitude=outside_latitude,
                    longitude=outside_longitude,
                ),
                process_location(
                    device_ids[1],
                    latitude=outside_latitude,
                    longitude=outside_longitude,
                ),
            )
        assert sum(event_count for _, _, event_count in concurrent_results) == (
            FENCES_PER_ASSET
        )
        async with session_factory() as session:
            asset_id = await session.scalar(
                select(Device.asset_id).where(Device.id_device == device_ids[1])
            )
            state_count = await session.scalar(
                select(func.count(GeoFenceAssetState.id_state)).where(
                    GeoFenceAssetState.asset_id == asset_id
                )
            )
            event_count = await session.scalar(
                select(func.count(GeoFenceEvent.id_event)).where(
                    GeoFenceEvent.device_id == device_ids[1]
                )
            )
        assert state_count == FENCES_PER_ASSET
        assert event_count == FENCES_PER_ASSET
    finally:
        await engine.dispose()
