from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.asset import Asset
from src.models.asset_group import AssetGroup, AssetGroupMember, GeoFenceAssetGroup
from src.models.geofence import GeoFence, GeoFenceAssignment, GeoFenceAssetState


class GeofenceMembershipService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_effective_geofence_ids_for_asset(self, asset_id: int) -> list[int]:
        result = await self.db.execute(self._effective_geofence_ids_for_asset_stmt(asset_id))
        return list(result.scalars().all())

    async def get_effective_asset_ids_for_geofence(self, geofence_id: int) -> list[int]:
        result = await self.db.execute(self._effective_asset_ids_for_geofence_stmt(geofence_id))
        return list(result.scalars().all())

    async def has_effective_assignment(self, geofence_id: int, asset_id: int) -> bool:
        memberships = self.effective_memberships_subquery()
        result = await self.db.execute(
            select(memberships.c.fence_id)
            .where(
                memberships.c.fence_id == geofence_id,
                memberships.c.asset_id == asset_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def delete_state_if_unassigned(self, geofence_id: int, asset_id: int) -> bool:
        if await self.has_effective_assignment(geofence_id, asset_id):
            return False

        result = await self.db.execute(
            select(GeoFenceAssetState).where(
                GeoFenceAssetState.fence_id == geofence_id,
                GeoFenceAssetState.asset_id == asset_id,
            )
        )
        state = result.scalar_one_or_none()
        if state is None:
            return False

        await self.db.delete(state)
        return True

    def _effective_geofence_ids_for_asset_stmt(self, asset_id: int):
        memberships = self.effective_memberships_subquery()
        return (
            select(memberships.c.fence_id)
            .where(memberships.c.asset_id == asset_id)
            .order_by(memberships.c.fence_id)
        )

    def _effective_asset_ids_for_geofence_stmt(self, geofence_id: int):
        memberships = self.effective_memberships_subquery()
        return (
            select(memberships.c.asset_id)
            .where(memberships.c.fence_id == geofence_id)
            .order_by(memberships.c.asset_id)
        )

    def effective_memberships_subquery(self):
        direct_assignments = (
            select(
                GeoFenceAssignment.fence_id.label("fence_id"),
                GeoFenceAssignment.asset_id.label("asset_id"),
            )
            .join(GeoFence, GeoFence.id_geofence == GeoFenceAssignment.fence_id)
            .join(Asset, Asset.id_asset == GeoFenceAssignment.asset_id)
            .where(
                GeoFenceAssignment.active.is_(True),
                GeoFenceAssignment.deleted == "N",
                GeoFence.active.is_(True),
                GeoFence.deleted == "N",
                Asset.deleted == "N",
            )
        )

        group_assignments = (
            select(
                GeoFenceAssetGroup.geofence_id.label("fence_id"),
                AssetGroupMember.asset_id.label("asset_id"),
            )
            .join(
                GeoFence,
                GeoFence.id_geofence == GeoFenceAssetGroup.geofence_id,
            )
            .join(
                AssetGroup,
                AssetGroup.id_asset_group == GeoFenceAssetGroup.asset_group_id,
            )
            .join(
                AssetGroupMember,
                AssetGroupMember.asset_group_id == AssetGroup.id_asset_group,
            )
            .join(Asset, Asset.id_asset == AssetGroupMember.asset_id)
            .where(
                GeoFenceAssetGroup.active.is_(True),
                GeoFenceAssetGroup.deleted == "N",
                GeoFence.active.is_(True),
                GeoFence.deleted == "N",
                AssetGroup.active.is_(True),
                AssetGroup.deleted == "N",
                AssetGroupMember.deleted == "N",
                Asset.deleted == "N",
            )
        )

        return union(direct_assignments, group_assignments).subquery()
