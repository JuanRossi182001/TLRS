from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.db.config.connection import get_db
from src.realtime.connection_manager import connection_manager
from src.routers import auth as auth_router
from src.routers import realtime as realtime_router
from src.schemas.realtime_auth import RealtimeConnectionScope
from src.schemas.user import TokenData
from src.service.crud_user import get_current_user
from src.service.realtime_auth_service import (
    RealtimeAuthForbiddenError,
    RealtimeAuthUnauthorizedError,
    RealtimeAuthUnavailableError,
)


def build_app(*, include_auth: bool = False, include_realtime: bool = False) -> FastAPI:
    app = FastAPI()
    if include_auth:
        app.include_router(auth_router.router)
    if include_realtime:
        app.include_router(realtime_router.router)

    async def fake_get_db():
        yield object()

    app.dependency_overrides[get_db] = fake_get_db
    return app


@pytest.fixture(autouse=True)
def clean_connection_manager():
    connection_manager._connections.clear()
    connection_manager._connection_ids.clear()
    yield
    connection_manager._connections.clear()
    connection_manager._connection_ids.clear()


def authenticated_user() -> TokenData:
    return TokenData(
        user_id=15,
        username="juan",
        client_id=4,
        is_admin=False,
        session_id=120,
    )


def connection_scope() -> RealtimeConnectionScope:
    return RealtimeConnectionScope(
        user_id=15,
        session_id=120,
        client_id=4,
        is_admin=False,
    )


def test_websocket_ticket_endpoint_requires_authentication() -> None:
    client = TestClient(build_app(include_auth=True))

    response = client.post("/auth/websocket-ticket")

    assert response.status_code == 401


def test_inactive_user_cannot_generate_ticket() -> None:
    app = build_app(include_auth=True)
    app.dependency_overrides[get_current_user] = authenticated_user
    client = TestClient(app)
    fake_service = type(
        "FakeRealtimeAuthService",
        (),
        {
            "issue_ticket": AsyncMock(
                side_effect=RealtimeAuthUnauthorizedError(
                    "Realtime authentication failed."
                )
            )
        },
    )()

    with patch("src.routers.auth.RealtimeAuthService", return_value=fake_service):
        response = client.post(
            "/auth/websocket-ticket",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 401


def test_redis_failure_while_generating_ticket_returns_503() -> None:
    app = build_app(include_auth=True)
    app.dependency_overrides[get_current_user] = authenticated_user
    client = TestClient(app)
    fake_service = type(
        "FakeRealtimeAuthService",
        (),
        {
            "issue_ticket": AsyncMock(
                side_effect=RealtimeAuthUnavailableError(
                    "Realtime authentication is unavailable."
                )
            )
        },
    )()

    with patch("src.routers.auth.RealtimeAuthService", return_value=fake_service):
        response = client.post(
            "/auth/websocket-ticket",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 503


def test_websocket_route_ignores_client_id_from_browser() -> None:
    client = TestClient(build_app(include_realtime=True))
    fake_service = type(
        "FakeRealtimeAuthService",
        (),
        {
            "consume_ticket": AsyncMock(return_value=connection_scope()),
            "validate_origin": Mock(return_value=None),
        },
    )()

    with patch("src.routers.realtime.RealtimeAuthService", return_value=fake_service):
        with client.websocket_connect(
            "/ws/locations?ticket=test-ticket&client_id=999",
            headers={"origin": "http://localhost:5173"},
        ):
            assert connection_manager.connection_count(4) == 1
            assert connection_manager.connection_count(999) == 0

    assert connection_manager.connection_count(4) == 0


def test_websocket_rejects_disallowed_origin() -> None:
    client = TestClient(build_app(include_realtime=True))
    fake_service = type(
        "FakeRealtimeAuthService",
        (),
        {
            "consume_ticket": AsyncMock(return_value=connection_scope()),
            "validate_origin": Mock(
                side_effect=RealtimeAuthForbiddenError(
                    "Realtime origin is not allowed."
                )
            ),
        },
    )()

    with patch("src.routers.realtime.RealtimeAuthService", return_value=fake_service):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/ws/locations?ticket=test-ticket",
                headers={"origin": "https://evil.example"},
            ):
                pass

    assert exc_info.value.code == 1008


def test_websocket_handles_redis_failure_during_handshake() -> None:
    client = TestClient(build_app(include_realtime=True))
    fake_service = type(
        "FakeRealtimeAuthService",
        (),
        {
            "consume_ticket": AsyncMock(
                side_effect=RealtimeAuthUnavailableError(
                    "Realtime authentication is unavailable."
                )
            ),
            "validate_origin": Mock(return_value=None),
        },
    )()

    with patch("src.routers.realtime.RealtimeAuthService", return_value=fake_service):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/ws/locations?ticket=test-ticket",
                headers={"origin": "http://localhost:5173"},
            ):
                pass

    assert exc_info.value.code == 1011


def test_temporary_websocket_route_is_not_registered() -> None:
    client = TestClient(build_app(include_realtime=True))

    assert "/ws/locations/{client_id}" not in {
        route.path for route in client.app.routes
    }
    assert client.get("/ws/locations/4").status_code == 404
