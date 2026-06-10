import json
from datetime import datetime
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select

from src.models.asset import Asset
from src.models.device import Device
from src.models.geofence import GeoFence, GeoFenceAssignment, GeoFenceEvent
from src.schemas.geofence import (
    GeoFenceActivationUpdate,
    GeoFenceAssignmentCreate,
    GeoFenceCreate,
    GeoFenceEventCreate,
    GeoFenceUpdate,
    GeoJSONMultiPolygon,
)
from src.service.crud_base import CrudBase


class GeoFenceService(CrudBase[GeoFence, GeoFenceCreate, GeoFenceUpdate]):
    model = GeoFence

    async def create_geofence(
        self,
        client_id: int,
        payload: GeoFenceCreate,
    ) -> dict[str, Any]:
        db_obj = GeoFence(
            client_id=client_id,
            name=payload.name,
            description=payload.description,
            shape=self._shape_to_wkt(payload.shape),
            active=payload.active,
        )

        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)

        geofence = await self.get_geofence_for_client(db_obj.id_geofence, client_id)
        return geofence

    async def get_geofences_by_client_id(
        self,
        client_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stmt = (
            self._geofence_select()
            .where(
                GeoFence.client_id == client_id,
                GeoFence.deleted == "N",
            )
            .order_by(GeoFence.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        return [self._format_geofence(row) for row in result.mappings().all()]

    async def get_geofence_for_client(
        self,
        geofence_id: int,
        client_id: int,
    ) -> dict[str, Any] | None:
        stmt = self._geofence_select().where(
            GeoFence.id_geofence == geofence_id,
            GeoFence.client_id == client_id,
            GeoFence.deleted == "N",
        )

        result = await self.db.execute(stmt)
        row = result.mappings().first()
        return self._format_geofence(row) if row else None

    async def update_geofence(
        self,
        geofence_id: int,
        client_id: int,
        payload: GeoFenceUpdate,
    ) -> dict[str, Any] | None:
        geofence = await self._get_geofence_model_for_client(geofence_id, client_id)
        if geofence is None:
            return None

        data = payload.model_dump(exclude_unset=True)
        shape = data.pop("shape", None)

        for field, value in data.items():
            setattr(geofence, field, value)

        if shape is not None:
            geofence.shape = self._shape_to_wkt(shape)

        self.db.add(geofence)
        await self.db.commit()

        return await self.get_geofence_for_client(geofence_id, client_id)

    async def delete_geofence(
        self,
        geofence_id: int,
        client_id: int,
    ) -> bool:
        geofence = await self._get_geofence_model_for_client(geofence_id, client_id)
        if geofence is None:
            return False

        geofence.deleted = "Y"
        geofence.active = False
        self.db.add(geofence)
        await self.db.commit()
        return True

    async def set_geofence_active(
        self,
        geofence_id: int,
        client_id: int,
        payload: GeoFenceActivationUpdate,
    ) -> dict[str, Any] | None:
        geofence = await self._get_geofence_model_for_client(geofence_id, client_id)
        if geofence is None:
            return None

        geofence.active = payload.active
        self.db.add(geofence)
        await self.db.commit()

        return await self.get_geofence_for_client(geofence_id, client_id)

    async def assign_assets(
        self,
        geofence_id: int,
        client_id: int,
        payload: GeoFenceAssignmentCreate,
    ) -> tuple[list[GeoFenceAssignment], list[int]] | None:
        geofence = await self._get_geofence_model_for_client(geofence_id, client_id)
        if geofence is None:
            return None

        requested_asset_ids = payload.asset_ids
        asset_result = await self.db.execute(
            select(Asset.id_asset).where(
                Asset.id_asset.in_(requested_asset_ids),
                Asset.client_id == client_id,
                Asset.deleted == "N",
            )
        )
        valid_asset_ids = set(asset_result.scalars().all())
        missing_asset_ids = [
            asset_id
            for asset_id in requested_asset_ids
            if asset_id not in valid_asset_ids
        ]
        if missing_asset_ids:
            return [], missing_asset_ids

        existing = await self.db.execute(
            select(GeoFenceAssignment).where(
                GeoFenceAssignment.fence_id == geofence_id,
                GeoFenceAssignment.asset_id.in_(requested_asset_ids),
                GeoFenceAssignment.deleted == "N",
                GeoFenceAssignment.active.is_(True),
            )
        )
        existing_assignments = {
            assignment.asset_id: assignment
            for assignment in existing.scalars().all()
        }

        new_assignments = [
            GeoFenceAssignment(
                fence_id=geofence_id,
                asset_id=asset_id,
                active=True,
            )
            for asset_id in requested_asset_ids
            if asset_id not in existing_assignments
        ]

        self.db.add_all(new_assignments)
        await self.db.commit()

        for assignment in new_assignments:
            await self.db.refresh(assignment)

        assignments_by_asset_id = {
            **existing_assignments,
            **{assignment.asset_id: assignment for assignment in new_assignments},
        }

        return [
            assignments_by_asset_id[asset_id]
            for asset_id in requested_asset_ids
        ], []

    async def get_assignments(
        self,
        geofence_id: int,
        client_id: int,
    ) -> list[GeoFenceAssignment] | None:
        geofence = await self._get_geofence_model_for_client(geofence_id, client_id)
        if geofence is None:
            return None

        result = await self.db.execute(
            select(GeoFenceAssignment)
            .where(
                GeoFenceAssignment.fence_id == geofence_id,
                GeoFenceAssignment.deleted == "N",
            )
            .order_by(GeoFenceAssignment.assigned_at.desc())
        )
        return list(result.scalars().all())

    async def deactivate_assignment(
        self,
        assignment_id: int,
        client_id: int,
    ) -> GeoFenceAssignment | None:
        result = await self.db.execute(
            select(GeoFenceAssignment)
            .join(GeoFence, GeoFence.id_geofence == GeoFenceAssignment.fence_id)
            .where(
                GeoFenceAssignment.id_assignment == assignment_id,
                GeoFenceAssignment.deleted == "N",
                GeoFence.client_id == client_id,
                GeoFence.deleted == "N",
            )
        )
        assignment = result.scalars().first()
        if assignment is None:
            return None

        assignment.active = False
        assignment.unassigned_at = datetime.utcnow()
        self.db.add(assignment)
        await self.db.commit()
        await self.db.refresh(assignment)
        return assignment

    async def create_event(self, payload: GeoFenceEventCreate) -> GeoFenceEvent:
        event = GeoFenceEvent(**payload.model_dump())
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def get_events_by_client_id(
        self,
        client_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(
                GeoFenceEvent.id_event,
                GeoFenceEvent.fence_id,
                GeoFence.name.label("geofence_name"),
                GeoFenceEvent.device_id,
                Device.name.label("device_name"),
                Device.serial.label("device_serial"),
                GeoFenceEvent.asset_id,
                Asset.asset_type.label("asset_type"),
                GeoFenceEvent.location_id,
                GeoFenceEvent.event_type,
                GeoFenceEvent.distance_to_boundary_meters,
                GeoFenceEvent.accuracy,
                GeoFenceEvent.created_at,
            )
            .join(GeoFence, GeoFence.id_geofence == GeoFenceEvent.fence_id)
            .join(Device, Device.id_device == GeoFenceEvent.device_id)
            .outerjoin(Asset, Asset.id_asset == GeoFenceEvent.asset_id)
            .where(
                GeoFence.client_id == client_id,
                GeoFence.deleted == "N",
            )
            .order_by(GeoFenceEvent.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.mappings().all())

    async def _get_geofence_model_for_client(
        self,
        geofence_id: int,
        client_id: int,
    ) -> GeoFence | None:
        result = await self.db.execute(
            select(GeoFence).where(
                GeoFence.id_geofence == geofence_id,
                GeoFence.client_id == client_id,
                GeoFence.deleted == "N",
            )
        )
        return result.scalars().first()

    def _geofence_select(self):
        return select(
            GeoFence.id_geofence,
            GeoFence.client_id,
            GeoFence.name,
            GeoFence.description,
            func.ST_AsGeoJSON(GeoFence.shape).label("shape"),
            GeoFence.active,
            GeoFence.created_at,
            GeoFence.updated_at,
        )

    def _format_geofence(self, row) -> dict[str, Any]:
        data = dict(row)
        data["shape"] = json.loads(data["shape"]) if data.get("shape") else None
        return data

    def _shape_to_wkt(self, shape: GeoJSONMultiPolygon | dict[str, Any]) -> WKTElement:
        if isinstance(shape, dict):
            shape = GeoJSONMultiPolygon(**shape)

        polygons = []
        for polygon in shape.coordinates:
            rings = []
            for ring in polygon:
                coordinates = ", ".join(f"{lon} {lat}" for lon, lat in ring)
                rings.append(f"({coordinates})")
            polygons.append(f"({', '.join(rings)})")

        return WKTElement(f"MULTIPOLYGON({', '.join(polygons)})", srid=4326)
