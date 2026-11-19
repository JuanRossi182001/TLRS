from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.config.connection import get_db
from src.routers.user import router
from src.schemas.user import TokenData
from src.service.crud_user import get_current_user


def _build_app(*, authenticated_user: TokenData | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def fake_get_db():
        yield object()

    app.dependency_overrides[get_db] = fake_get_db
    if authenticated_user is not None:
        app.dependency_overrides[get_current_user] = lambda: authenticated_user
    return app


def _payload() -> dict:
    return {
        "name": "created-user",
        "email": "created@example.com",
        "id_client": 42,
    }


def test_anonymous_user_cannot_create_account() -> None:
    with patch("src.routers.user.UserService") as user_service:
        response = TestClient(_build_app()).post("/user", json=_payload())

    assert response.status_code == 401
    user_service.assert_not_called()


def test_non_admin_cannot_assign_admin_or_client_scope() -> None:
    user = TokenData(
        user_id=7,
        username="customer",
        client_id=42,
        is_admin=False,
    )
    with patch("src.routers.user.UserService") as user_service:
        response = TestClient(
            _build_app(authenticated_user=user)
        ).post("/user", json=_payload())

    assert response.status_code == 403
    user_service.assert_not_called()


def test_admin_can_create_user() -> None:
    admin = TokenData(
        user_id=1,
        username="admin",
        is_admin=True,
    )
    created_user = SimpleNamespace(
        id_user=8,
        name="created-user",
        email="created@example.com",
        id_client=42,
        is_admin=False,
    )
    service = SimpleNamespace(create_invited_user=AsyncMock(return_value=created_user))

    with (
        patch("src.routers.user.UserService", return_value=service),
        patch(
            "src.routers.user.AccountEmailService.create_token",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = TestClient(
            _build_app(authenticated_user=admin)
        ).post("/user", json=_payload())

    assert response.status_code == 201
    assert response.json()["id_user"] == 8
    service.create_invited_user.assert_awaited_once()
    assert response.json()["is_admin"] is False
    assert response.json()["invitation_email_sent"] is False
    assert "password" not in response.json()
