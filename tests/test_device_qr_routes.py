from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.config.connection import get_db
from src.models.asset import AssetStatus
from src.models.device import DeviceState
from src.routers.device import router
from src.schemas.device import DeviceQrAssetSummary, DeviceQrResolveResponse
from src.schemas.user import TokenData
from src.service.crud_user import get_current_user


def _app(*, is_admin: bool, client_id: int | None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def fake_get_db():
        yield object()

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        user_id=5,
        username="admin" if is_admin else "ranch-user",
        client_id=client_id,
        is_admin=is_admin,
    )
    return app


def _resolved_device() -> DeviceQrResolveResponse:
    return DeviceQrResolveResponse(
        id_device=29,
        serial="MANEA-0029",
        name="Collar 0029",
        type="COLLAR",
        state=DeviceState.OFF,
        active=False,
        asset=DeviceQrAssetSummary(
            id_asset=1842,
            serial="1842",
            asset_type="CATTLE",
            status=AssetStatus.ACTIVE,
        ),
    )


def test_user_resolves_qr_only_within_their_authenticated_client_scope() -> None:
    service = SimpleNamespace(resolve_qr_token=AsyncMock(return_value=_resolved_device()))
    access_validation = AsyncMock(return_value=True)

    with (
        patch("src.routers.device.DeviceService", return_value=service),
        patch("src.routers.device.validate_user_service_access", access_validation),
    ):
        response = TestClient(_app(is_admin=False, client_id=7)).get(
            f"/devices/by-qr/{'q' * 43}"
        )

    assert response.status_code == 200
    assert response.json()["id_device"] == 29
    assert response.json()["asset"]["serial"] == "1842"
    assert "client_id" not in response.json()
    assert "qr_token" not in response.json()
    access_validation.assert_awaited_once()
    service.resolve_qr_token.assert_awaited_once_with("q" * 43, client_id=7)


def test_invalid_or_cross_tenant_qr_returns_generic_not_found() -> None:
    service = SimpleNamespace(resolve_qr_token=AsyncMock(return_value=None))

    with (
        patch("src.routers.device.DeviceService", return_value=service),
        patch(
            "src.routers.device.validate_user_service_access",
            AsyncMock(return_value=True),
        ),
    ):
        response = TestClient(_app(is_admin=False, client_id=7)).get(
            f"/devices/by-qr/{'q' * 43}"
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Device not found."
    service.resolve_qr_token.assert_awaited_once_with("q" * 43, client_id=7)


def test_non_admin_without_client_scope_cannot_resolve_qr() -> None:
    service_factory = patch("src.routers.device.DeviceService")
    access_validation = AsyncMock(return_value=True)

    with (
        service_factory as mocked_service,
        patch("src.routers.device.validate_user_service_access", access_validation),
    ):
        response = TestClient(_app(is_admin=False, client_id=None)).get(
            f"/devices/by-qr/{'q' * 43}"
        )

    assert response.status_code == 404
    access_validation.assert_awaited_once()
    mocked_service.assert_not_called()


def test_admin_can_get_qr_token_for_device() -> None:
    service = SimpleNamespace(get_qr_token=AsyncMock(return_value="q" * 43))

    with patch("src.routers.device.DeviceService", return_value=service):
        response = TestClient(_app(is_admin=True, client_id=None)).get(
            "/devices/29/qr"
        )

    assert response.status_code == 200
    assert response.json() == {"qr_token": "q" * 43}
    service.get_qr_token.assert_awaited_once_with(29)


def test_non_admin_cannot_read_admin_qr_token() -> None:
    with patch("src.routers.device.DeviceService") as service_factory:
        response = TestClient(_app(is_admin=False, client_id=7)).get(
            "/devices/29/qr"
        )

    assert response.status_code == 403
    service_factory.assert_not_called()
