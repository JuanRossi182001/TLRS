from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.asset import Asset, AssetStatus
from src.models.device import Device, DeviceState
from src.models.device_asset_assignment import DeviceAssetAssignment


class DeviceAssignmentError(ValueError):
    pass


class DeviceAssignmentInvariantError(DeviceAssignmentError):
    pass


class DeviceAssignmentService:
    """Owns the current and historical device-to-asset assignment invariant."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def assign_asset(self, device_id: int, asset_id: int) -> Device | None:
        try:
            device = await self._get_device_for_update(device_id)
            if device is None:
                return None

            asset = await self._get_assignable_asset(device, asset_id)
            active_assignment = await self._get_active_assignment_for_update(device_id)

            if device.asset_id == asset.id_asset:
                if active_assignment is None:
                    raise DeviceAssignmentInvariantError(
                        "Device current asset has no active assignment history."
                    )
                if active_assignment.asset_id != asset.id_asset:
                    raise DeviceAssignmentInvariantError(
                        "Device current asset does not match its active assignment history."
                    )
                return device

            self._validate_current_assignment(device, active_assignment)
            await self._ensure_asset_is_available(asset.id_asset, device.id_device)

            assignment_time = self._utcnow()
            if active_assignment is not None:
                active_assignment.unassigned_at = assignment_time

            self.db.add(
                DeviceAssetAssignment(
                    device_id=device.id_device,
                    asset_id=asset.id_asset,
                    assigned_at=assignment_time,
                )
            )
            device.asset_id = asset.id_asset
            self.db.add(device)
            await self.db.commit()
            await self.db.refresh(device)
            return device
        except Exception:
            await self.db.rollback()
            raise

    async def release_asset(self, device_id: int) -> Device | None:
        try:
            device = await self._get_device_for_update(device_id)
            if device is None:
                return None

            active_assignment = await self._get_active_assignment_for_update(device_id)
            if device.asset_id is None:
                if active_assignment is not None:
                    raise DeviceAssignmentInvariantError(
                        "Device has an active assignment history but no current asset."
                    )
                return device

            self._validate_current_assignment(device, active_assignment)
            active_assignment.unassigned_at = self._utcnow()
            device.asset_id = None
            device.active = False
            device.state = DeviceState.OFF
            self.db.add(device)
            await self.db.commit()
            await self.db.refresh(device)
            return device
        except Exception:
            await self.db.rollback()
            raise

    async def create_initial_assignment(
        self,
        device: Device,
        asset: Asset,
    ) -> Device:
        """Persist a new device and its first assignment in one transaction."""
        try:
            if device.id_device is not None:
                raise DeviceAssignmentError(
                    "Initial assignment requires a device that has not been persisted."
                )
            if device.client_id is None:
                raise DeviceAssignmentError(
                    "Device must belong to a client before assigning an asset."
                )
            if asset.id_asset is None:
                raise DeviceAssignmentError("Asset must be persisted before assignment.")
            if asset.client_id != device.client_id:
                raise DeviceAssignmentError("Asset not found for this device client.")
            if asset.deleted != "N":
                raise DeviceAssignmentError("Asset not found for this device client.")
            if asset.status != AssetStatus.ACTIVE:
                raise DeviceAssignmentError("Asset is inactive.")
            if device.asset_id is not None:
                raise DeviceAssignmentInvariantError(
                    "New device must not have an asset before its initial assignment."
                )

            await self._ensure_asset_is_available(asset.id_asset)
            assignment_time = self._utcnow()
            device.asset_id = asset.id_asset
            self.db.add(device)
            await self.db.flush()
            self.db.add(
                DeviceAssetAssignment(
                    device_id=device.id_device,
                    asset_id=asset.id_asset,
                    assigned_at=assignment_time,
                )
            )
            await self.db.commit()
            await self.db.refresh(device)
            return device
        except Exception:
            await self.db.rollback()
            raise

    async def get_active_assignment_for_device(
        self,
        device_id: int,
    ) -> DeviceAssetAssignment | None:
        stmt = select(DeviceAssetAssignment).where(
            DeviceAssetAssignment.device_id == device_id,
            DeviceAssetAssignment.unassigned_at.is_(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_assignment_for_device_at(
        self,
        device_id: int,
        timestamp: datetime,
    ) -> DeviceAssetAssignment | None:
        stmt = select(DeviceAssetAssignment).where(
            DeviceAssetAssignment.device_id == device_id,
            DeviceAssetAssignment.assigned_at <= timestamp,
            or_(
                DeviceAssetAssignment.unassigned_at.is_(None),
                DeviceAssetAssignment.unassigned_at > timestamp,
            ),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_asset_device_assignments(
        self,
        asset_id: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[DeviceAssetAssignment]:
        if date_from is not None and date_to is not None and date_from >= date_to:
            raise DeviceAssignmentError("date_from must be earlier than date_to.")

        stmt = select(DeviceAssetAssignment).where(
            DeviceAssetAssignment.asset_id == asset_id,
        )
        if date_to is not None:
            stmt = stmt.where(DeviceAssetAssignment.assigned_at < date_to)
        if date_from is not None:
            stmt = stmt.where(
                or_(
                    DeviceAssetAssignment.unassigned_at.is_(None),
                    DeviceAssetAssignment.unassigned_at > date_from,
                )
            )
        stmt = stmt.order_by(DeviceAssetAssignment.assigned_at)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _get_device_for_update(self, device_id: int) -> Device | None:
        stmt = (
            select(Device)
            .where(Device.id_device == device_id, Device.deleted == "N")
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_assignable_asset(self, device: Device, asset_id: int) -> Asset:
        if device.client_id is None:
            raise DeviceAssignmentError(
                "Device must belong to a client before assigning an asset."
            )

        stmt = select(Asset).where(
            Asset.id_asset == asset_id,
            Asset.client_id == device.client_id,
            Asset.deleted == "N",
        )
        result = await self.db.execute(stmt)
        asset = result.scalar_one_or_none()
        if asset is None:
            raise DeviceAssignmentError("Asset not found for this device client.")
        if asset.status != AssetStatus.ACTIVE:
            raise DeviceAssignmentError("Asset is inactive.")
        return asset

    async def _get_active_assignment_for_update(
        self,
        device_id: int,
    ) -> DeviceAssetAssignment | None:
        stmt = (
            select(DeviceAssetAssignment)
            .where(
                DeviceAssetAssignment.device_id == device_id,
                DeviceAssetAssignment.unassigned_at.is_(None),
            )
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _ensure_asset_is_available(
        self,
        asset_id: int,
        device_id: int | None = None,
    ) -> None:
        conditions = [Device.asset_id == asset_id, Device.deleted == "N"]
        if device_id is not None:
            conditions.append(Device.id_device != device_id)

        stmt = select(Device.id_device).where(*conditions).with_for_update()
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise DeviceAssignmentError("Asset already has a device assigned.")

    @staticmethod
    def _validate_current_assignment(
        device: Device,
        active_assignment: DeviceAssetAssignment | None,
    ) -> None:
        if device.asset_id is None:
            if active_assignment is not None:
                raise DeviceAssignmentInvariantError(
                    "Device has an active assignment history but no current asset."
                )
            return
        if active_assignment is None:
            raise DeviceAssignmentInvariantError(
                "Device current asset has no active assignment history."
            )
        if active_assignment.asset_id != device.asset_id:
            raise DeviceAssignmentInvariantError(
                "Device current asset does not match its active assignment history."
            )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
