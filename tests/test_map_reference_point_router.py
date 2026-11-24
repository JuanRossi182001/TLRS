from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.config.connection import get_db
from src.routers import map_reference_point
from src.schemas.user import TokenData
from src.service.crud_user import get_current_user


def _read_point(client_id: int = 42) -> dict:
    now = datetime(2026, 11, 19, 12, 0, 0)
    return {
        "id_map_reference_point": 7,
        "client_id": client_id,
        "category": "WATER_TROUGH",
        "other_type": None,
        "name": "North water",
        "latitude": -33.25,
        "longitude": -65.25,
        "note": None,
        "created_at": now,
        "updated_at": now,
    }


def _build_client(
    *,
    is_admin: bool = False,
    client_id: int | None = 42,
) -> TestClient:
    app = FastAPI()
    app.include_router(map_reference_point.router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        user_id=1,
        username="test-user",
        client_id=client_id,
        is_admin=is_admin,
    )
    return TestClient(app)


def test_client_user_can_create_and_list_points(monkeypatch) -> None:
    created_with: list[dict] = []

    class FakeService:
        def __init__(self, _db):
            pass

        async def create(self, **kwargs):
            created_with.append(kwargs)
            return SimpleNamespace(id_map_reference_point=7)

        async def get_read_model_for_client(self, point_id, scoped_client_id):
            assert point_id == 7
            return _read_point(scoped_client_id)

        async def list_read_models_for_client(self, client_id, *, skip, limit):
            assert skip == 0
            assert limit == 500
            return [_read_point(client_id)]

    monkeypatch.setattr(map_reference_point, "MapReferencePointService", FakeService)
    client = _build_client()

    response = client.post(
        "/map-reference-points",
        json={
            "category": "WATER_TROUGH",
            "name": "North water",
            "latitude": -33.25,
            "longitude": -65.25,
        },
    )
    assert response.status_code == 201
    assert response.json()["client_id"] == 42
    assert created_with[0]["client_id"] == 42

    response = client.get("/map-reference-points")
    assert response.status_code == 200
    assert response.json()[0]["category"] == "WATER_TROUGH"
    assert response.json()[0]["latitude"] == -33.25


def test_client_user_cannot_choose_another_client_scope(monkeypatch) -> None:
    class UnexpectedService:
        def __init__(self, _db):
            raise AssertionError("service must not be called for a foreign scope")

    monkeypatch.setattr(
        map_reference_point,
        "MapReferencePointService",
        UnexpectedService,
    )
    response = _build_client().get("/map-reference-points?client_id=99")
    assert response.status_code == 404


def test_admin_must_select_explicit_client_scope(monkeypatch) -> None:
    class FakeService:
        def __init__(self, _db):
            pass

        async def list_read_models_for_client(self, client_id, *, skip, limit):
            return [_read_point(client_id)]

    monkeypatch.setattr(map_reference_point, "MapReferencePointService", FakeService)
    client = _build_client(is_admin=True, client_id=None)

    missing_scope = client.get("/map-reference-points")
    assert missing_scope.status_code == 400

    selected_scope = client.get("/map-reference-points?client_id=99")
    assert selected_scope.status_code == 200
    assert selected_scope.json()[0]["client_id"] == 99


def test_other_requires_custom_type() -> None:
    response = _build_client().post(
        "/map-reference-points",
        json={
            "category": "OTHER",
            "name": "Reference",
            "latitude": 0,
            "longitude": 0,
        },
    )
    assert response.status_code == 422


def test_client_id_is_not_accepted_in_request_body() -> None:
    response = _build_client().post(
        "/map-reference-points",
        json={
            "client_id": 99,
            "category": "CORRAL",
            "name": "Corral",
            "latitude": 0,
            "longitude": 0,
        },
    )
    assert response.status_code == 422
