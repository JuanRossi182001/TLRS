from datetime import datetime

from sqlalchemy import func, select, text
from geoalchemy2.elements import WKTElement

import pytest

from src.application.telemetry.normalized_telemetry import NormalizedTelemetry
from src.models.client import Client
from src.models.asset import Asset, AssetStatus
from src.models.device import Device, DeviceCommunicationProtocol, DeviceState
from src.models.device_command import DeviceCommand, DeviceCommandStatus, DeviceCommandType
from src.models.geofence import (
    FenceEventType,
    GeoFence,
    GeoFenceAssignment,
    GeoFenceEvent,
)
from src.models.location import Location
from src.service.location_ingestion_service import LocationIngestionService


pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_alembic_installs_postgis_and_location_geography_type(
    test_session_factory,
) -> None:
    async with test_session_factory() as session:
        postgis_version = await session.scalar(text("SELECT PostGIS_Full_Version()"))
        location_point_type = await session.scalar(
            text(
                """
                SELECT format_type(attribute.atttypid, attribute.atttypmod)
                FROM pg_attribute AS attribute
                JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                JOIN pg_namespace AS schema ON schema.oid = relation.relnamespace
                WHERE schema.nspname = 'public'
                  AND relation.relname = 'locations'
                  AND attribute.attname = 'point'
                  AND NOT attribute.attisdropped
                """
            )
        )

    assert "POSTGIS=" in postgis_version.upper()
    assert location_point_type.lower() == "geography(point,4326)"


async def test_location_ingestion_persists_postgis_point_and_marks_device_online(
    test_session_factory,
) -> None:
    received_at = datetime(2026, 10, 20, 12, 0, 0)

    async with test_session_factory() as session:
        async with session.begin():
            client = Client(name="Pytest client", email="pytest@example.test")
            session.add(client)
            await session.flush()

            device = Device(
                serial="PYTEST-DEVICE-001",
                name="Pytest device",
                type="COLLAR",
                client_id=client.id_client,
                communication_protocol=DeviceCommunicationProtocol.MQTT,
                state=DeviceState.OFF,
                active=False,
            )
            session.add(device)
            await session.flush()

            location = await LocationIngestionService(session).persist_location(
                device=device,
                normalized_telemetry=NormalizedTelemetry(
                    device_timestamp=datetime(2026, 10, 20, 11, 59, 55),
                    latitude=-33.3012,
                    longitude=-66.3371,
                    altitude=520.0,
                    accuracy=5.0,
                ),
                received_at=received_at,
            )

            persisted_point = await session.scalar(
                select(func.ST_AsText(Location.point)).where(
                    Location.id_location == location.id_location
                )
            )

            assert location.id_location is not None
            assert persisted_point == "POINT(-66.3371 -33.3012)"
            assert device.state == DeviceState.ON
            assert device.last_seen_at == received_at


async def test_location_transition_creates_geofence_event_and_downlinks(
    test_session_factory,
) -> None:
    async with test_session_factory() as session:
        async with session.begin():
            client = Client(name="Fence test client", email="fence@example.test")
            session.add(client)
            await session.flush()

            asset = Asset(
                asset_type="CATTLE",
                serial="PYTEST-COW-001",
                client_id=client.id_client,
                status=AssetStatus.ACTIVE,
            )
            session.add(asset)
            await session.flush()

            device = Device(
                serial="PYTEST-CHIRPSTACK-001",
                name="Pytest ChirpStack device",
                type="COLLAR",
                client_id=client.id_client,
                asset_id=asset.id_asset,
                active=True,
                state=DeviceState.OFF,
                communication_protocol=DeviceCommunicationProtocol.CHIRPSTACK,
                chirpstack_dev_eui="0102030405060708",
                chirpstack_application_id="pytest-app",
            )
            geofence = GeoFence(
                client_id=client.id_client,
                name="Test pasture",
                shape=WKTElement(
                    "MULTIPOLYGON(((-66.34 -33.31, -66.32 -33.31, "
                    "-66.32 -33.29, -66.34 -33.29, -66.34 -33.31)))",
                    srid=4326,
                ),
                active=True,
            )
            session.add_all([device, geofence])
            await session.flush()
            session.add(
                GeoFenceAssignment(
                    asset_id=asset.id_asset,
                    fence_id=geofence.id_geofence,
                    active=True,
                )
            )
            await session.flush()

            ingestion = LocationIngestionService(session)
            await ingestion.persist_location(
                device,
                NormalizedTelemetry(
                    device_timestamp=datetime(2026, 10, 20, 11, 0, 0),
                    latitude=-33.30,
                    longitude=-66.33,
                    accuracy=5,
                ),
                received_at=datetime(2026, 10, 20, 11, 0, 1),
            )
            await ingestion.persist_location(
                device,
                NormalizedTelemetry(
                    device_timestamp=datetime(2026, 10, 20, 11, 1, 0),
                    latitude=-33.30,
                    longitude=-66.30,
                    accuracy=5,
                ),
                received_at=datetime(2026, 10, 20, 11, 1, 1),
            )

            event = await session.scalar(
                select(GeoFenceEvent).where(
                    GeoFenceEvent.fence_id == geofence.id_geofence,
                    GeoFenceEvent.asset_id == asset.id_asset,
                )
            )
            assert event is not None
            commands = (
                await session.scalars(
                    select(DeviceCommand)
                    .where(DeviceCommand.geofence_event_id == event.id_event)
                    .order_by(DeviceCommand.command_seq)
                )
            ).all()

            assert event.event_type == FenceEventType.EXITED
            assert len(commands) == 2
            assert [command.command_seq for command in commands] == [1, 2]
            assert [command.command_type for command in commands] == [
                DeviceCommandType.SET_REPORT_INTERVAL,
                DeviceCommandType.WARNING_SOUND,
            ]
            assert all(command.status == DeviceCommandStatus.PENDING for command in commands)
            assert all(command.asset_id == asset.id_asset for command in commands)
