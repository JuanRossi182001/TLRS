import pytest
from sqlalchemy import select

from src.models.client import Client
from src.models.map_reference_point import (
    MapReferencePoint,
    MapReferencePointCategory,
)
from src.service.map_reference_point_service import (
    MapReferencePointService,
    MapReferencePointValidationError,
)


@pytest.mark.integration
@pytest.mark.anyio
async def test_map_reference_points_are_scoped_and_soft_deleted(
    test_session_factory,
) -> None:
    async with test_session_factory() as session:
        first_client = Client(name="Map reference first", email="map-first@example.test")
        second_client = Client(name="Map reference second", email="map-second@example.test")
        session.add_all([first_client, second_client])
        await session.flush()

        service = MapReferencePointService(session)
        point = await service.create(
            client_id=first_client.id_client,
            category=MapReferencePointCategory.WATER_TROUGH,
            name="North water",
            latitude=-33.25,
            longitude=-65.25,
            note="Near the north paddock",
        )

        assert point.point is not None
        read_point = await service.get_read_model_for_client(
            point.id_map_reference_point,
            first_client.id_client,
        )
        assert read_point is not None
        assert read_point["latitude"] == pytest.approx(-33.25)
        assert read_point["longitude"] == pytest.approx(-65.25)
        assert await service.get_for_client(
            point.id_map_reference_point,
            second_client.id_client,
        ) is None
        assert await service.list_for_client(second_client.id_client) == []

        updated = await service.update(
            point.id_map_reference_point,
            client_id=first_client.id_client,
            category=MapReferencePointCategory.OTHER,
            other_type="Salt lick",
            name="North reference",
            latitude=-33.5,
            longitude=-65.5,
            note=None,
        )
        assert updated is not None
        assert updated.category is MapReferencePointCategory.OTHER
        assert updated.other_type == "Salt lick"
        assert updated.note is None

        assert await service.delete(
            point.id_map_reference_point,
            second_client.id_client,
        ) is False
        assert await service.delete(
            point.id_map_reference_point,
            first_client.id_client,
        ) is True
        assert await service.get_for_client(
            point.id_map_reference_point,
            first_client.id_client,
        ) is None

        stored = await session.scalar(
            select(MapReferencePoint).where(
                MapReferencePoint.id_map_reference_point
                == point.id_map_reference_point
            )
        )
        assert stored is not None
        assert stored.deleted == "Y"


def test_other_category_requires_custom_type() -> None:
    with pytest.raises(MapReferencePointValidationError, match="Other type is required"):
        MapReferencePointService._validate_fields(
            category=MapReferencePointCategory.OTHER,
            name="Reference",
            latitude=0,
            longitude=0,
            other_type=None,
        )


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (90.1, 0),
        (0, -180.1),
        (float("nan"), 0),
        (0, float("inf")),
    ],
)
def test_coordinates_must_be_valid(latitude: float, longitude: float) -> None:
    with pytest.raises(MapReferencePointValidationError):
        MapReferencePointService._validate_fields(
            category=MapReferencePointCategory.CORRAL,
            name="Reference",
            latitude=latitude,
            longitude=longitude,
            other_type=None,
        )
