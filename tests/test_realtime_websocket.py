import unittest
from unittest.mock import AsyncMock, Mock, patch

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


class RealtimeRouterTests(unittest.TestCase):
    def tearDown(self) -> None:
        connection_manager._connections.clear()
        connection_manager._connection_ids.clear()

    def _build_app(self, *, include_auth: bool = False, include_realtime: bool = False) -> FastAPI:
        app = FastAPI()

        if include_auth:
            app.include_router(auth_router.router)
        if include_realtime:
            app.include_router(realtime_router.router)

        async def fake_get_db():
            yield object()

        app.dependency_overrides[get_db] = fake_get_db
        return app

    def test_websocket_ticket_endpoint_requires_authentication(self) -> None:
        app = self._build_app(include_auth=True)
        client = TestClient(app)

        response = client.post("/auth/websocket-ticket")

        self.assertEqual(response.status_code, 401)

    def test_inactive_user_cannot_generate_ticket(self) -> None:
        app = self._build_app(include_auth=True)
        app.dependency_overrides[get_current_user] = lambda: TokenData(
            user_id=15,
            username="juan",
            client_id=4,
            is_admin=False,
            session_id=120,
        )
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

        self.assertEqual(response.status_code, 401)

    def test_redis_failure_while_generating_ticket_returns_503(self) -> None:
        app = self._build_app(include_auth=True)
        app.dependency_overrides[get_current_user] = lambda: TokenData(
            user_id=15,
            username="juan",
            client_id=4,
            is_admin=False,
            session_id=120,
        )
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

        self.assertEqual(response.status_code, 503)

    def test_websocket_route_ignores_client_id_from_browser(self) -> None:
        app = self._build_app(include_realtime=True)
        client = TestClient(app)
        fake_service = type(
            "FakeRealtimeAuthService",
            (),
            {
                "consume_ticket": AsyncMock(
                    return_value=RealtimeConnectionScope(
                        user_id=15,
                        session_id=120,
                        client_id=4,
                        is_admin=False,
                    )
                ),
                "validate_origin": Mock(return_value=None),
            },
        )()

        with patch("src.routers.realtime.RealtimeAuthService", return_value=fake_service):
            with client.websocket_connect(
                "/ws/locations?ticket=test-ticket&client_id=999",
                headers={"origin": "http://localhost:5173"},
            ):
                self.assertEqual(connection_manager.connection_count(4), 1)
                self.assertEqual(connection_manager.connection_count(999), 0)

        self.assertEqual(connection_manager.connection_count(4), 0)

    def test_websocket_rejects_disallowed_origin(self) -> None:
        app = self._build_app(include_realtime=True)
        client = TestClient(app)
        fake_service = type(
            "FakeRealtimeAuthService",
            (),
            {
                "consume_ticket": AsyncMock(
                    return_value=RealtimeConnectionScope(
                        user_id=15,
                        session_id=120,
                        client_id=4,
                        is_admin=False,
                    )
                ),
                "validate_origin": Mock(
                    side_effect=RealtimeAuthForbiddenError(
                        "Realtime origin is not allowed."
                    )
                ),
            },
        )()

        with patch("src.routers.realtime.RealtimeAuthService", return_value=fake_service):
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with client.websocket_connect(
                    "/ws/locations?ticket=test-ticket",
                    headers={"origin": "https://evil.example"},
                ):
                    pass

        self.assertEqual(ctx.exception.code, 1008)

    def test_websocket_handles_redis_failure_during_handshake(self) -> None:
        app = self._build_app(include_realtime=True)
        client = TestClient(app)
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
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with client.websocket_connect(
                    "/ws/locations?ticket=test-ticket",
                    headers={"origin": "http://localhost:5173"},
                ):
                    pass

        self.assertEqual(ctx.exception.code, 1011)

    def test_temporary_websocket_route_is_not_registered(self) -> None:
        app = self._build_app(include_realtime=True)
        client = TestClient(app)

        self.assertNotIn(
            "/ws/locations/{client_id}",
            {route.path for route in app.routes},
        )
        self.assertEqual(client.get("/ws/locations/4").status_code, 404)


if __name__ == "__main__":
    unittest.main()
