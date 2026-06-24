from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.asset import Asset
from src.models.asset_group import AssetGroup, AssetGroupMember, GeoFenceAssetGroup
from src.models.device import Device
from src.models.geofence import GeoFence
from src.schemas.asset_group import (
    AssetGroupActivationUpdate,
    AssetGroupCreate,
    AssetGroupMembersUpdate,
    AssetGroupUpdate,
    GeofenceAssetGroupsAssign,
    GeofenceAssetGroupsRemove,
)
from src.service.crud_base import CrudBase
from src.service.geofence_membership_service import GeofenceMembershipService


class AssetGroupNotFoundError(Exception):
    def __init__(self, detail: str):
        self.detail = detail


class AssetGroupConflictError(Exception):
    def __init__(self, detail: str):
        self.detail = detail


class AssetGroupValidationError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        asset_ids: list[int] | None = None,
        asset_group_ids: list[int] | None = None,
    ):
        self.detail = detail
        self.asset_ids = asset_ids or []
        self.asset_group_ids = asset_group_ids or []

class AssetGroupService(CrudBase[AssetGroup, AssetGroupCreate, AssetGroupUpdate]):
    model = AssetGroup

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def create_asset_group(
        self,
        client_id: int,
        payload: AssetGroupCreate,
    ) -> dict[str, Any]:
        asset_ids = payload.asset_ids or []
        await self._validate_asset_ids_for_client(client_id, asset_ids)

        asset_group = AssetGroup(
            client_id=client_id,
            name=payload.name,
            description=payload.description,
            active=True,
        )
        self.db.add(asset_group)
        await self.db.flush()

        if asset_ids:
            self.db.add_all(
                [
                    AssetGroupMember(
                        asset_group_id=asset_group.id_asset_group,
                        asset_id=asset_id,
                    )
                    for asset_id in asset_ids
                ]
            )

        await self.db.commit()
        return await self.get_asset_group_detail_for_client(
            asset_group.id_asset_group,
            client_id,
        )

    async def get_asset_groups_by_client_id(
        self,
        client_id: int,
        *,
        active: bool | None = None,
        skip: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = self._asset_group_summary_select().where(
            AssetGroup.client_id == client_id,
            AssetGroup.deleted == "N",
        )

        if active is not None:
            stmt = stmt.where(AssetGroup.active.is_(active))

        if search:
            search_term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    AssetGroup.name.ilike(search_term),
                    AssetGroup.description.ilike(search_term),
                )
            )

        result = await self.db.execute(
            stmt.order_by(AssetGroup.created_at.desc()).offset(skip).limit(limit)
        )
        return [dict(row) for row in result.mappings().all()]

    async def get_asset_group_detail_for_client(
        self,
        asset_group_id: int,
        client_id: int,
    ) -> dict[str, Any] | None:
        summary_stmt = self._asset_group_summary_select().where(
            AssetGroup.id_asset_group == asset_group_id,
            AssetGroup.client_id == client_id,
            AssetGroup.deleted == "N",
        )
        summary_result = await self.db.execute(summary_stmt)
        summary = summary_result.mappings().first()
        if summary is None:
            return None

        members = await self._get_asset_group_members(asset_group_id)
        return {
            **dict(summary),
            "members": members,
        }

    async def update_asset_group(
        self,
        asset_group_id: int,
        client_id: int,
        payload: AssetGroupUpdate,
    ) -> dict[str, Any] | None:
        asset_group = await self._get_asset_group_model_for_client(asset_group_id, client_id)
        if asset_group is None:
            return None

        data = payload.model_dump(exclude_unset=True)
        asset_ids = data.pop("asset_ids", None)

        for field, value in data.items():
            setattr(asset_group, field, value)

        self.db.add(asset_group)

        if asset_ids is not None:
            await self._replace_members(
                asset_group_id=asset_group_id,
                client_id=client_id,
                asset_ids=asset_ids,
            )

        await self.db.commit()
        return await self.get_asset_group_detail_for_client(asset_group_id, client_id)

    async def set_asset_group_active(
        self,
        asset_group_id: int,
        client_id: int,
        payload: AssetGroupActivationUpdate,
    ) -> dict[str, Any] | None:
        asset_group = await self._get_asset_group_model_for_client(asset_group_id, client_id)
        if asset_group is None:
            return None

        membership_pairs: set[tuple[int, int]] = set()
        if asset_group.active and not payload.active:
            active_geofence_ids = await self._get_active_geofence_ids_for_group(asset_group_id)
            active_asset_ids = await self._get_active_asset_ids_for_group(asset_group_id)
            membership_pairs = self._build_membership_pairs(
                geofence_ids=active_geofence_ids,
                asset_ids=active_asset_ids,
            )

        asset_group.active = payload.active
        self.db.add(asset_group)

        await self._cleanup_effective_states(membership_pairs)
        await self.db.commit()

        return await self.get_asset_group_detail_for_client(asset_group_id, client_id)

    async def add_members(
        self,
        asset_group_id: int,
        client_id: int,
        payload: AssetGroupMembersUpdate,
    ) -> dict[str, Any]:
        asset_group = await self._get_asset_group_model_for_client(asset_group_id, client_id)
        if asset_group is None:
            raise AssetGroupNotFoundError("Asset group not found.")

        asset_ids = payload.asset_ids
        await self._validate_asset_ids_for_client(client_id, asset_ids)

        existing_result = await self.db.execute(
            select(AssetGroupMember).where(
                AssetGroupMember.asset_group_id == asset_group_id,
                AssetGroupMember.asset_id.in_(asset_ids),
            )
        )
        existing_by_asset_id = {
            member.asset_id: member for member in existing_result.scalars().all()
        }

        for asset_id in asset_ids:
            existing = existing_by_asset_id.get(asset_id)
            if existing is None:
                self.db.add(
                    AssetGroupMember(
                        asset_group_id=asset_group_id,
                        asset_id=asset_id,
                    )
                )
                continue

            if existing.deleted == "Y":
                existing.deleted = "N"
                self.db.add(existing)

        await self.db.commit()
        return await self.get_asset_group_detail_for_client(asset_group_id, client_id)

    async def remove_members(
        self,
        asset_group_id: int,
        client_id: int,
        asset_ids: list[int],
    ) -> dict[str, Any]:
        asset_group = await self._get_asset_group_model_for_client(asset_group_id, client_id)
        if asset_group is None:
            raise AssetGroupNotFoundError("Asset group not found.")

        active_geofence_ids = await self._get_active_geofence_ids_for_group(asset_group_id)

        result = await self.db.execute(
            select(AssetGroupMember).where(
                AssetGroupMember.asset_group_id == asset_group_id,
                AssetGroupMember.asset_id.in_(asset_ids),
                AssetGroupMember.deleted == "N",
            )
        )
        active_members = list(result.scalars().all())
        membership_pairs = self._build_membership_pairs(
            geofence_ids=active_geofence_ids,
            asset_ids=[member.asset_id for member in active_members],
        )

        for member in active_members:
            member.deleted = "Y"
            self.db.add(member)

        await self._cleanup_effective_states(membership_pairs)
        await self.db.commit()
        return await self.get_asset_group_detail_for_client(asset_group_id, client_id)

    async def assign_groups_to_geofence(
        self,
        geofence_id: int,
        client_id: int,
        payload: GeofenceAssetGroupsAssign,
    ) -> list[GeoFenceAssetGroup]:
        geofence = await self._get_geofence_for_client(geofence_id, client_id)
        if geofence is None:
            raise AssetGroupNotFoundError("Geofence not found.")

        asset_group_ids = payload.asset_group_ids
        await self._validate_asset_group_ids_for_client(
            client_id,
            asset_group_ids,
            require_active=True,
        )

        existing_result = await self.db.execute(
            select(GeoFenceAssetGroup).where(
                GeoFenceAssetGroup.geofence_id == geofence_id,
                GeoFenceAssetGroup.asset_group_id.in_(asset_group_ids),
                GeoFenceAssetGroup.deleted == "N",
                GeoFenceAssetGroup.active.is_(True),
            )
        )
        existing_by_group_id = {
            assignment.asset_group_id: assignment
            for assignment in existing_result.scalars().all()
        }

        new_assignments = [
            GeoFenceAssetGroup(
                geofence_id=geofence_id,
                asset_group_id=asset_group_id,
                active=True,
            )
            for asset_group_id in asset_group_ids
            if asset_group_id not in existing_by_group_id
        ]

        self.db.add_all(new_assignments)
        await self.db.commit()

        for assignment in new_assignments:
            await self.db.refresh(assignment)

        assignments_by_group_id = {
            **existing_by_group_id,
            **{
                assignment.asset_group_id: assignment
                for assignment in new_assignments
            },
        }

        return [assignments_by_group_id[group_id] for group_id in asset_group_ids]

    async def remove_groups_from_geofence(
        self,
        geofence_id: int,
        client_id: int,
        payload: GeofenceAssetGroupsRemove,
    ) -> list[GeoFenceAssetGroup]:
        geofence = await self._get_geofence_for_client(geofence_id, client_id)
        if geofence is None:
            raise AssetGroupNotFoundError("Geofence not found.")

        result = await self.db.execute(
            select(GeoFenceAssetGroup).where(
                GeoFenceAssetGroup.geofence_id == geofence_id,
                GeoFenceAssetGroup.asset_group_id.in_(payload.asset_group_ids),
                GeoFenceAssetGroup.deleted == "N",
                GeoFenceAssetGroup.active.is_(True),
            )
        )
        assignments = list(result.scalars().all())
        now = datetime.utcnow()
        membership_pairs: set[tuple[int, int]] = set()

        for assignment in assignments:
            active_asset_ids = await self._get_active_asset_ids_for_group(assignment.asset_group_id)
            membership_pairs.update(
                self._build_membership_pairs(
                    geofence_ids=[geofence_id],
                    asset_ids=active_asset_ids,
                )
            )

        for assignment in assignments:
            assignment.active = False
            assignment.unassigned_at = now
            self.db.add(assignment)

        await self._cleanup_effective_states(membership_pairs)
        await self.db.commit()
        return assignments

    async def get_geofence_asset_group_assignments(
        self,
        geofence_id: int,
        client_id: int,
    ) -> list[GeoFenceAssetGroup] | None:
        geofence = await self._get_geofence_for_client(geofence_id, client_id)
        if geofence is None:
            return None

        result = await self.db.execute(
            select(GeoFenceAssetGroup)
            .where(
                GeoFenceAssetGroup.geofence_id == geofence_id,
                GeoFenceAssetGroup.deleted == "N",
            )
            .order_by(GeoFenceAssetGroup.assigned_at.desc())
        )
        return list(result.scalars().all())

    async def _replace_members(
        self,
        *,
        asset_group_id: int,
        client_id: int,
        asset_ids: list[int],
    ) -> None:
        await self._validate_asset_ids_for_client(client_id, asset_ids)
        requested_asset_ids = set(asset_ids)
        active_geofence_ids = await self._get_active_geofence_ids_for_group(asset_group_id)

        result = await self.db.execute(
            select(AssetGroupMember).where(
                AssetGroupMember.asset_group_id == asset_group_id,
            )
        )
        members = list(result.scalars().all())
        members_by_asset_id = {member.asset_id: member for member in members}
        removed_asset_ids = [
            member.asset_id
            for member in members
            if member.deleted == "N" and member.asset_id not in requested_asset_ids
        ]
        membership_pairs = self._build_membership_pairs(
            geofence_ids=active_geofence_ids,
            asset_ids=removed_asset_ids,
        )

        for member in members:
            if member.deleted == "N" and member.asset_id not in requested_asset_ids:
                member.deleted = "Y"
                self.db.add(member)

        for asset_id in asset_ids:
            existing = members_by_asset_id.get(asset_id)
            if existing is None:
                self.db.add(
                    AssetGroupMember(
                        asset_group_id=asset_group_id,
                        asset_id=asset_id,
                    )
                )
                continue

            if existing.deleted == "Y":
                existing.deleted = "N"
                self.db.add(existing)

        await self._cleanup_effective_states(membership_pairs)

    async def _validate_asset_ids_for_client(
        self,
        client_id: int,
        asset_ids: list[int],
    ) -> None:
        if not asset_ids:
            return

        result = await self.db.execute(
            select(Asset.id_asset).where(
                Asset.id_asset.in_(asset_ids),
                Asset.client_id == client_id,
                Asset.deleted == "N",
            )
        )
        valid_asset_ids = set(result.scalars().all())
        missing_asset_ids = [asset_id for asset_id in asset_ids if asset_id not in valid_asset_ids]
        if missing_asset_ids:
            raise AssetGroupValidationError(
                "One or more assets were not found for this client.",
                asset_ids=missing_asset_ids,
            )

    async def _validate_asset_group_ids_for_client(
        self,
        client_id: int,
        asset_group_ids: list[int],
        *,
        require_active: bool = False,
    ) -> None:
        if not asset_group_ids:
            return

        result = await self.db.execute(
            select(AssetGroup).where(
                AssetGroup.id_asset_group.in_(asset_group_ids),
                AssetGroup.client_id == client_id,
                AssetGroup.deleted == "N",
            )
        )
        groups = list(result.scalars().all())
        groups_by_id = {group.id_asset_group: group for group in groups}

        missing_group_ids = [
            asset_group_id
            for asset_group_id in asset_group_ids
            if asset_group_id not in groups_by_id
        ]
        if missing_group_ids:
            raise AssetGroupValidationError(
                "One or more asset groups were not found for this client.",
                asset_group_ids=missing_group_ids,
            )

        if require_active:
            inactive_group_ids = [
                asset_group_id
                for asset_group_id, group in groups_by_id.items()
                if not group.active
            ]
            if inactive_group_ids:
                raise AssetGroupConflictError(
                    "Inactive asset groups cannot be assigned to geofences."
                )

    async def _get_asset_group_model_for_client(
        self,
        asset_group_id: int,
        client_id: int,
    ) -> AssetGroup | None:
        result = await self.db.execute(
            select(AssetGroup).where(
                AssetGroup.id_asset_group == asset_group_id,
                AssetGroup.client_id == client_id,
                AssetGroup.deleted == "N",
            )
        )
        return result.scalars().first()

    async def _get_geofence_for_client(
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

    async def _get_asset_group_members(self, asset_group_id: int) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(
                Asset.id_asset.label("asset_id"),
                Asset.asset_type.label("asset_name"),
                Asset.asset_type,
                Asset.serial.label("asset_serial"),
                Device.id_device.label("device_id"),
                Device.serial.label("device_serial"),
                Device.name.label("device_name"),
                Device.active.label("device_active"),
                Device.state.label("device_state"),
            )
            .select_from(AssetGroupMember)
            .join(Asset, Asset.id_asset == AssetGroupMember.asset_id)
            .outerjoin(
                Device,
                and_(
                    Device.asset_id == Asset.id_asset,
                    Device.deleted == "N",
                ),
            )
            .where(
                AssetGroupMember.asset_group_id == asset_group_id,
                AssetGroupMember.deleted == "N",
                Asset.deleted == "N",
            )
            .order_by(Asset.id_asset)
        )
        return [dict(row) for row in result.mappings().all()]

    async def _get_active_asset_ids_for_group(self, asset_group_id: int) -> list[int]:
        result = await self.db.execute(
            select(Asset.id_asset)
            .join(AssetGroupMember, AssetGroupMember.asset_id == Asset.id_asset)
            .where(
                AssetGroupMember.asset_group_id == asset_group_id,
                AssetGroupMember.deleted == "N",
                Asset.deleted == "N",
            )
            .order_by(Asset.id_asset)
        )
        return list(result.scalars().all())

    async def _get_active_geofence_ids_for_group(self, asset_group_id: int) -> list[int]:
        result = await self.db.execute(
            select(GeoFenceAssetGroup.geofence_id)
            .where(
                GeoFenceAssetGroup.asset_group_id == asset_group_id,
                GeoFenceAssetGroup.deleted == "N",
                GeoFenceAssetGroup.active.is_(True),
            )
            .order_by(GeoFenceAssetGroup.geofence_id)
        )
        return list(result.scalars().all())

    async def _cleanup_effective_states(
        self,
        membership_pairs: set[tuple[int, int]],
    ) -> None:
        if not membership_pairs:
            return

        membership_service = GeofenceMembershipService(self.db)
        for geofence_id, asset_id in membership_pairs:
            await membership_service.delete_state_if_unassigned(geofence_id, asset_id)

    def _build_membership_pairs(
        self,
        *,
        geofence_ids: list[int],
        asset_ids: list[int],
    ) -> set[tuple[int, int]]:
        return {
            (geofence_id, asset_id)
            for geofence_id in geofence_ids
            for asset_id in asset_ids
        }

    def _asset_group_summary_select(self):
        return (
            select(
                AssetGroup.id_asset_group,
                AssetGroup.client_id,
                AssetGroup.name,
                AssetGroup.description,
                AssetGroup.active,
                func.count(Asset.id_asset).label("total_assets"),
                AssetGroup.created_at,
                AssetGroup.updated_at,
            )
            .outerjoin(
                AssetGroupMember,
                and_(
                    AssetGroupMember.asset_group_id == AssetGroup.id_asset_group,
                    AssetGroupMember.deleted == "N",
                ),
            )
            .outerjoin(
                Asset,
                and_(
                    Asset.id_asset == AssetGroupMember.asset_id,
                    Asset.deleted == "N",
                ),
            )
            .group_by(
                AssetGroup.id_asset_group,
                AssetGroup.client_id,
                AssetGroup.name,
                AssetGroup.description,
                AssetGroup.active,
                AssetGroup.created_at,
                AssetGroup.updated_at,
            )
        )
