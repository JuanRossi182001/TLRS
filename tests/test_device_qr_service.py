import pytest

from src.models.asset import Asset, AssetStatus
from src.models.device import Device, DeviceState
from src.service.crud_device import DeviceService


class QueryResult:
    def __init__(self, row) -> None:
        self.row = row

    def one_or_none(self):
        return self.row


class RecordingSession:
    def __init__(self, row=None) -> None:
        self.row = row
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return QueryResult(self.row)


def _device(*, client_id: int | None, asset_id: int | None) -> Device:
    return Device(
        id_device=29,
        serial="MANEA-0029",
        qr_token="q" * 43,
        name="Collar 0029",
        type="COLLAR",
        state=DeviceState.OFF,
        active=asset_id is not None,
        client_id=client_id,
        asset_id=asset_id,
        deleted="N",
    )


@pytest.mark.anyio
async def test_qr_resolution_returns_minimal_device_and_asset_summary() -> None:
    device = _device(client_id=7, asset_id=18)
    asset = Asset(
        id_asset=18,
        serial="1842",
        asset_type="CATTLE",
        status=AssetStatus.ACTIVE,
        client_id=7,
        deleted="N",
    )
    session = RecordingSession((device, asset))

    response = await DeviceService(session).resolve_qr_token("q" * 43, client_id=7)

    assert response is not None
    assert response.id_device == 29
    assert response.serial == "MANEA-0029"
    assert response.state == DeviceState.OFF
    assert response.asset is not None
    assert response.asset.serial == "1842"
    assert response.asset.status == AssetStatus.ACTIVE

    statement = str(session.statement)
    params = session.statement.compile().params
    assert "devices.qr_token" in statement
    assert "devices.deleted" in statement
    assert "coalesce(devices.client_id, assets.client_id)" in statement
    assert "coalesce(devices.client_id, assets.client_id) = assets.client_id" in statement
    assert 7 in params.values()
    assert "client_id" not in response.model_dump()
    assert "qr_token" not in response.model_dump()


@pytest.mark.anyio
async def test_qr_resolution_includes_legacy_asset_client_fallback() -> None:
    session = RecordingSession((_device(client_id=None, asset_id=18), None))

    await DeviceService(session).resolve_qr_token("q" * 43, client_id=7)

    statement = str(session.statement)
    assert "coalesce(devices.client_id, assets.client_id)" in statement


@pytest.mark.anyio
async def test_qr_resolution_returns_unassigned_offline_device() -> None:
    device = _device(client_id=7, asset_id=None)
    session = RecordingSession((device, None))

    response = await DeviceService(session).resolve_qr_token("q" * 43, client_id=7)

    assert response is not None
    assert response.asset is None
    assert response.state == DeviceState.OFF
    assert response.active is False


@pytest.mark.anyio
async def test_admin_qr_resolution_is_global_but_still_excludes_soft_deleted_devices() -> None:
    session = RecordingSession((_device(client_id=None, asset_id=None), None))

    await DeviceService(session).resolve_qr_token("q" * 43, client_id=None)

    statement = str(session.statement)
    assert "devices.qr_token" in statement
    assert "devices.deleted" in statement
    assert "coalesce(devices.client_id, assets.client_id) = assets.client_id" in statement
    assert "coalesce_1" not in session.statement.compile().params


def test_qr_token_index_is_unique_and_not_partial() -> None:
    indexes = {index.name: index for index in Device.__table__.indexes}
    qr_index = indexes["uq_devices_qr_token"]

    assert qr_index.unique is True
    assert qr_index.dialect_options["postgresql"].get("where") is None
