from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.config.connection import get_db
from src.routers.client import router
from src.schemas.user import TokenData
from src.service.crud_user import get_current_user


def _build_client(**overrides):
    values = {
        "id_client": 42,
        "name": "Ranch",
        "email": "ops@example.com",
        "deleted": "N",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _build_app(*, is_admin: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def fake_get_db():
        yield object()

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        user_id=1,
        username="admin" if is_admin else "customer",
        client_id=None if is_admin else 42,
        is_admin=is_admin,
    )
    return app


def test_admin_can_create_client_and_email_is_normalized() -> None:
    service = SimpleNamespace(create_client=AsyncMock(return_value=_build_client()))
    client_service = patch(
        "src.routers.client.ClientService",
        return_value=service,
    )

    with client_service:
        response = TestClient(_build_app()).post(
            "/admin/clients",
            json={"name": "Ranch", "email": " OPS@Example.com "},
        )

    assert response.status_code == 201
    assert response.json() == {
        "id_client": 42,
        "name": "Ranch",
        "email": "ops@example.com",
    }
    assert service.create_client.await_args.args[0].email == "ops@example.com"


def test_admin_can_read_update_and_soft_delete_client() -> None:
    service = SimpleNamespace(
        get_client=AsyncMock(return_value=_build_client()),
        update_client=AsyncMock(return_value=_build_client(name="Updated Ranch")),
        delete_client=AsyncMock(return_value=_build_client(deleted="Y")),
    )

    with patch("src.routers.client.ClientService", return_value=service):
        test_client = TestClient(_build_app())
        get_response = test_client.get("/admin/clients/42")
        patch_response = test_client.patch(
            "/admin/clients/42",
            json={"name": "Updated Ranch"},
        )
        delete_response = test_client.delete("/admin/clients/42")

    assert get_response.status_code == 200
    assert patch_response.status_code == 200
    assert patch_response.json()["name"] == "Updated Ranch"
    assert delete_response.status_code == 204
    service.delete_client.assert_awaited_once_with(42)


@pytest.mark.parametrize(
    ("method", "url", "kwargs"),
    [
        (
            "post",
            "/admin/clients",
            {"json": {"name": "X", "email": "x@example.com"}},
        ),
        ("get", "/admin/clients/42", {}),
        ("patch", "/admin/clients/42", {"json": {"name": "Updated"}}),
        ("delete", "/admin/clients/42", {}),
    ],
)
def test_non_admin_cannot_manage_clients(method: str, url: str, kwargs: dict) -> None:
    with patch("src.routers.client.ClientService") as client_service:
        response = getattr(TestClient(_build_app(is_admin=False)), method)(
            url,
            **kwargs,
        )

    assert response.status_code == 403
    client_service.assert_not_called()


def test_duplicate_email_returns_conflict() -> None:
    from src.service.crud_client import ClientEmailConflictError

    service = SimpleNamespace(
        create_client=AsyncMock(
            side_effect=ClientEmailConflictError(
                "A client with this email already exists."
            )
        )
    )
    with patch("src.routers.client.ClientService", return_value=service):
        response = TestClient(_build_app()).post(
            "/admin/clients",
            json={"name": "Other", "email": "ops@example.com"},
        )

    assert response.status_code == 409


def test_client_update_requires_at_least_one_non_null_field() -> None:
    test_client = TestClient(_build_app())

    empty_response = test_client.patch("/admin/clients/42", json={})
    null_response = test_client.patch("/admin/clients/42", json={"name": None})

    assert empty_response.status_code == 422
    assert null_response.status_code == 422
