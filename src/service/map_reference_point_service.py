import math
from datetime import datetime

from geoalchemy2.elements import WKTElement
from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.map_reference_point import (
    MapReferencePoint,
    MapReferencePointCategory,
)


class MapReferencePointValidationError(ValueError):
    """Raised when a map reference point violates domain constraints."""


class MapReferencePointService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        client_id: int,
        category: MapReferencePointCategory,
        name: str,
        latitude: float,
        longitude: float,
        note: str | None = None,
        other_type: str | None = None,
    ) -> MapReferencePoint:
        normalized = self._validate_fields(
            category=category,
            name=name,
            latitude=latitude,
            longitude=longitude,
            other_type=other_type,
        )
        point = MapReferencePoint(
            client_id=client_id,
            category=category,
            other_type=normalized,
            name=name.strip(),
            point=self._point_wkt(latitude, longitude),
            note=note,
        )
        self.db.add(point)
        await self.db.commit()
        await self.db.refresh(point)
        return point

    async def list_for_client(
        self,
        client_id: int,
    ) -> list[MapReferencePoint]:
        result = await self.db.execute(
            select(MapReferencePoint)
            .where(
                MapReferencePoint.client_id == client_id,
                MapReferencePoint.deleted == "N",
            )
            .order_by(MapReferencePoint.id_map_reference_point)
        )
        return list(result.scalars().all())

    async def list_read_models_for_client(
        self,
        client_id: int,
        *,
        skip: int = 0,
        limit: int = 500,
    ) -> list[dict]:
        result = await self.db.execute(
            self._read_select()
            .where(
                MapReferencePoint.client_id == client_id,
                MapReferencePoint.deleted == "N",
            )
            .order_by(MapReferencePoint.id_map_reference_point)
            .offset(skip)
            .limit(limit)
        )
        return [self._format_read_row(row) for row in result.all()]

    async def get_read_model_for_client(
        self,
        point_id: int,
        client_id: int,
    ) -> dict | None:
        result = await self.db.execute(
            self._read_select().where(
                MapReferencePoint.id_map_reference_point == point_id,
                MapReferencePoint.client_id == client_id,
                MapReferencePoint.deleted == "N",
            )
        )
        row = result.first()
        return self._format_read_row(row) if row else None

    async def get_for_client(
        self,
        point_id: int,
        client_id: int,
    ) -> MapReferencePoint | None:
        result = await self.db.execute(
            select(MapReferencePoint).where(
                MapReferencePoint.id_map_reference_point == point_id,
                MapReferencePoint.client_id == client_id,
                MapReferencePoint.deleted == "N",
            )
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        point_id: int,
        *,
        client_id: int,
        category: MapReferencePointCategory,
        name: str,
        latitude: float,
        longitude: float,
        note: str | None = None,
        other_type: str | None = None,
    ) -> MapReferencePoint | None:
        point = await self.get_for_client(point_id, client_id)
        if point is None:
            return None

        normalized = self._validate_fields(
            category=category,
            name=name,
            latitude=latitude,
            longitude=longitude,
            other_type=other_type,
        )
        point.category = category
        point.other_type = normalized
        point.name = name.strip()
        point.point = self._point_wkt(latitude, longitude)
        point.note = note
        point.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(point)
        return point

    async def delete(self, point_id: int, client_id: int) -> bool:
        point = await self.get_for_client(point_id, client_id)
        if point is None:
            return False

        point.deleted = "Y"
        point.updated_at = datetime.utcnow()
        await self.db.commit()
        return True

    @staticmethod
    def _validate_fields(
        *,
        category: MapReferencePointCategory,
        name: str,
        latitude: float,
        longitude: float,
        other_type: str | None,
    ) -> str | None:
        if not isinstance(category, MapReferencePointCategory):
            raise MapReferencePointValidationError("Invalid map reference category.")
        if not name or not name.strip():
            raise MapReferencePointValidationError("Name cannot be empty.")
        if len(name.strip()) > 255:
            raise MapReferencePointValidationError("Name cannot exceed 255 characters.")
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise MapReferencePointValidationError("Latitude must be between -90 and 90.")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise MapReferencePointValidationError(
                "Longitude must be between -180 and 180."
            )

        if category is MapReferencePointCategory.OTHER:
            normalized = other_type.strip() if other_type else ""
            if not normalized:
                raise MapReferencePointValidationError(
                    "Other type is required for the OTHER category."
                )
            if len(normalized) > 100:
                raise MapReferencePointValidationError(
                    "Other type cannot exceed 100 characters."
                )
            return normalized

        if other_type is not None:
            raise MapReferencePointValidationError(
                "Other type is only allowed for the OTHER category."
            )
        return None

    @staticmethod
    def _point_wkt(latitude: float, longitude: float) -> WKTElement:
        return WKTElement(f"POINT({longitude} {latitude})", srid=4326)

    @staticmethod
    def _read_select():
        point_geometry = cast(
            MapReferencePoint.point,
            Geometry(geometry_type="POINT", srid=4326),
        )
        return select(
            MapReferencePoint,
            func.ST_Y(point_geometry).label("latitude"),
            func.ST_X(point_geometry).label("longitude"),
        )

    @staticmethod
    def _format_read_row(row) -> dict:
        point, latitude, longitude = row
        return {
            "id_map_reference_point": point.id_map_reference_point,
            "client_id": point.client_id,
            "category": point.category,
            "other_type": point.other_type,
            "name": point.name,
            "latitude": latitude,
            "longitude": longitude,
            "note": point.note,
            "created_at": point.created_at,
            "updated_at": point.updated_at,
        }
