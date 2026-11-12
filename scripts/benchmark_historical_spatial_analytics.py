"""Disposable-only volume benchmark. Run with python -m scripts.benchmark_historical_spatial_analytics.

All inserted rows are rolled back. Requires TEST_DATABASE_URL pointing to the
isolated tlrs_test database on localhost:55432, with migrations already applied.
"""

import argparse
import asyncio
import cProfile
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import pstats
from statistics import median
import time
import tracemalloc
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.application.analytics.spatial_grid import SpatialGridConfig
from src.application.analytics.performance_profile import ProcessingProfile
from src.models.asset import Asset, AssetStatus
from src.models.client import Client
from src.models.device import Device, DeviceCommunicationProtocol, DeviceState
from src.models.device_asset_assignment import DeviceAssetAssignment
from src.service.historical_spatial_analytics_service import (
    HistoricalAnalyticsLimits, HistoricalSpatialAnalyticsService,
)
from src.service.historical_spatial_analytics_repository import HistoricalSpatialAnalyticsRepository


SCENARIOS = {"1x24h": (1, 1), "1x30d": (1, 30),
             "50x7d": (50, 7), "100x30d": (100, 30),
             "10x24h": (10, 1), "50x24h": (50, 1)}
START = datetime(2026, 9, 1)


def reference_result(result, ids):
    """Normalize fixture-generated animal IDs; preserve every field and cell."""
    ordered_ids = {asset_id: index for index, asset_id in enumerate(ids)}
    buckets = []
    for bucket in result.buckets:
        data = asdict(bucket)
        data["asset_id"] = ordered_ids[bucket.asset_id]
        data["bucket_start"] = data["bucket_start"].isoformat()
        data["bucket_end"] = data["bucket_end"].isoformat()
        buckets.append(data)
    metadata = asdict(result.metadata)
    metadata["window_start"] = metadata["window_start"].isoformat()
    metadata["window_end"] = metadata["window_end"].isoformat()
    return {"buckets": buckets, "metadata": metadata}


def process_memory_megabytes() -> tuple[float, float]:
    """Linux process RSS and process-lifetime high water mark (not server RSS)."""
    values = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(("VmRSS:", "VmHWM:")):
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) / 1024
    return values["VmRSS"], values["VmHWM"]


async def benchmark(label: str, *, cadence: int = 900, pattern: str = "static",
                    repetitions: int = 1, profile_enabled: bool = False,
                    cpu_profile: bool = False, reference: Path | None = None,
                    write_reference: bool = False, explain_only: bool = False) -> None:
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        raise RuntimeError("TEST_DATABASE_URL is required for disposable-only benchmarks.")
    url = make_url(raw_url)
    if (
        url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.port != 55432 or url.database != "tlrs_test" or url.username != "tlrs_test"
    ):
        raise RuntimeError("Refusing to benchmark any database outside disposable tlrs_test.")
    animals, days = SCENARIOS[label]
    if cadence not in (5, 15, 30, 600, 900) or repetitions < 1 or repetitions > 5:
        raise ValueError("Unsupported cadence or repetitions (1..5).")
    if pattern not in ("static", "mixed"):
        raise ValueError("Unsupported benchmark pattern.")
    count_per_device = days * 86400 // cadence
    if animals * count_per_device > 500_000:
        raise ValueError("Fixture would exceed the 500,000-location safety cap.")
    engine = create_async_engine(url.set(drivername="postgresql+asyncpg"), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.begin()
            try:
                suffix = uuid4().hex
                client = Client(name="Analytics benchmark", email=f"analytics-benchmark-{suffix}@example.test")
                session.add(client)
                await session.flush()
                ids = []
                first_device_id = None
                for index in range(animals):
                    asset = Asset(asset_type="CATTLE", serial=f"ANALYTICS-BENCH-{suffix}-{index}",
                                  client_id=client.id_client, status=AssetStatus.ACTIVE)
                    session.add(asset)
                    await session.flush()
                    device = Device(serial=f"ANALYTICS-BENCH-DEVICE-{suffix}-{index}",
                                    name="Analytics benchmark collar", type="COLLAR",
                                    client_id=client.id_client, asset_id=asset.id_asset,
                                    active=True, state=DeviceState.OFF,
                                    communication_protocol=DeviceCommunicationProtocol.MQTT)
                    session.add(device)
                    await session.flush()
                    if first_device_id is None:
                        first_device_id = device.id_device
                    session.add(DeviceAssetAssignment(device_id=device.id_device,
                                                      asset_id=asset.id_asset, assigned_at=START))
                    ids.append(asset.id_asset)
                    await session.execute(text("""
                        INSERT INTO locations (device_id, latitude, longitude, accuracy,
                                               device_timestamp, received_at, deleted)
                        SELECT :device_id, -33.651,
                               CASE WHEN :pattern = 'mixed' AND (n / 120) % 2 = 1
                                    THEN -65.46338 ELSE -65.472 END,
                               CASE WHEN :pattern = 'mixed' AND n % 90 = 30 THEN 255 ELSE 1 END,
                               CAST(:start AS timestamp) + n * (:step * interval '1 second')
                                   + CASE WHEN :pattern = 'mixed' THEN (n / 240) * interval '10 minutes'
                                          ELSE interval '0 second' END,
                               CAST(:start AS timestamp) + n * (:step * interval '1 second')
                                   + CASE WHEN :pattern = 'mixed' THEN (n / 240) * interval '10 minutes'
                                          ELSE interval '0 second' END + interval '1 second',
                               'N'
                        FROM generate_series(0, :count - 1) AS n
                    """), {"device_id": device.id_device, "start": START,
                            "count": count_per_device, "step": cadence, "pattern": pattern})
                await session.flush()
                if explain_only:
                    await session.execute(text("ANALYZE locations"))
                    stmt = text("""
                        EXPLAIN (ANALYZE, BUFFERS)
                        SELECT id_location, COALESCE(device_timestamp, received_at)
                        FROM locations
                        WHERE device_id = :device_id AND deleted = 'N'
                          AND COALESCE(device_timestamp, received_at) >= :start
                          AND COALESCE(device_timestamp, received_at) < :end
                        ORDER BY COALESCE(device_timestamp, received_at), id_location
                        LIMIT 500
                    """)
                    rows = (await session.execute(stmt, {
                        "device_id": first_device_id, "start": START,
                        "end": START + timedelta(days=days),
                    })).all()
                    print("\n".join(row[0] for row in rows))
                    return
                readings = []
                reference_value = None
                for index in range(repetitions):
                    measured_profile = ProcessingProfile() if profile_enabled else None
                    service = HistoricalSpatialAnalyticsService(
                        session, repository=HistoricalSpatialAnalyticsRepository(session),
                        profile=measured_profile,
                    )
                    tracemalloc.start()
                    tracemalloc.reset_peak()
                    profiler = cProfile.Profile() if cpu_profile and index == 0 else None
                    started = time.perf_counter()
                    if profiler is not None:
                        profiler.enable()
                    try:
                        result = await service.analyze_assets(
                            client_id=client.id_client, asset_ids=ids, window_start=START,
                            window_end=START + timedelta(days=days),
                            grid_config=SpatialGridConfig("EPSG:32720", 25),
                            limits=HistoricalAnalyticsLimits(max_query_seconds=300),
                        )
                    finally:
                        if profiler is not None:
                            profiler.disable()
                    seconds = time.perf_counter() - started
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    rss, rss_peak = process_memory_megabytes()
                    normalized = reference_result(result, ids)
                    if reference_value is not None and normalized != reference_value:
                        raise AssertionError("Identical repeated queries returned different analytics.")
                    reference_value = normalized
                    if reference is not None and not write_reference:
                        if normalized != json.loads(reference.read_text()):
                            raise AssertionError("Analytics differ from pre-optimization reference.")
                    reading = {"scenario": label, "cadence_seconds": cadence, "pattern": pattern,
                               "pass": index + 1, "fixtures": animals * count_per_device,
                               "processed_locations": result.metadata.processed_location_count,
                               "elapsed_seconds": round(seconds, 4),
                               "python_peak_megabytes": round(peak / 1_000_000, 3),
                               "process_rss_megabytes": round(rss, 3),
                               "process_max_rss_megabytes": round(rss_peak, 3),
                               "results": len(result.buckets),
                               "observed_seconds": result.metadata.observed_seconds,
                               "dwell_seconds": result.metadata.dwell_seconds}
                    if measured_profile is not None:
                        reading["profile"] = measured_profile.as_dict()
                    readings.append(reading)
                    print(json.dumps(reading))
                    if profiler is not None:
                        stream = io.StringIO()
                        pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(25)
                        print("cProfile (diagnostic only, timings not comparable):\n" + stream.getvalue())
                if reference is not None and write_reference:
                    if reference.exists():
                        raise FileExistsError("Refusing to overwrite an existing baseline reference.")
                    reference.write_text(json.dumps(reference_value, indent=2) + "\n")
                durations = [r["elapsed_seconds"] for r in readings]
                print(json.dumps({"scenario": label, "cadence_seconds": cadence, "pattern": pattern,
                                  "repetitions": repetitions, "min_seconds": min(durations),
                                  "median_seconds": median(durations), "max_seconds": max(durations)}))
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--cadence", type=int, default=900, choices=(5, 15, 30, 600, 900))
    parser.add_argument("--pattern", default="static", choices=("static", "mixed"))
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--cprofile", action="store_true")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--write-reference", action="store_true")
    parser.add_argument("--explain-only", action="store_true")
    args = parser.parse_args()
    if args.write_reference and args.reference is None:
        parser.error("--write-reference requires --reference")
    asyncio.run(benchmark(args.scenario, cadence=args.cadence, pattern=args.pattern,
                          repetitions=args.repetitions, profile_enabled=args.profile,
                          cpu_profile=args.cprofile, reference=args.reference,
                          write_reference=args.write_reference,
                          explain_only=args.explain_only))
