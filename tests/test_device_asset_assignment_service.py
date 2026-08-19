import unittest
from datetime import datetime

from src.models.asset import Asset, AssetStatus
from src.models.device import Device, DeviceState
from src.models.device_asset_assignment import DeviceAssetAssignment
from src.service.device_assignment_service import (
    DeviceAssignmentError,
    DeviceAssignmentService,
)


ASSIGNMENT_TIME = datetime(2026, 8, 18, 12, 0, 0)


class FakeSession:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.added = []
        self.commit_error = commit_error
        self.committed = False
        self.rolled_back = False
        self.next_device_id = 100
        self.device: Device | None = None
        self.active_assignment: DeviceAssetAssignment | None = None
        self._original_device_asset_id: int | None = None
        self._original_assignment_unassigned_at: datetime | None = None

    def track(self, device: Device, assignment: DeviceAssetAssignment | None) -> None:
        self.device = device
        self.active_assignment = assignment
        self._original_device_asset_id = device.asset_id
        self._original_assignment_unassigned_at = (
            assignment.unassigned_at if assignment is not None else None
        )

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if isinstance(value, Device) and value.id_device is None:
                value.id_device = self.next_device_id
                self.next_device_id += 1

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True
        if self.device is not None:
            self.device.asset_id = self._original_device_asset_id
        if self.active_assignment is not None:
            self.active_assignment.unassigned_at = self._original_assignment_unassigned_at
        self.added = [
            value
            for value in self.added
            if not isinstance(value, DeviceAssetAssignment)
        ]

    async def refresh(self, value) -> None:
        return None


class FakeCollectionResult:
    def __init__(self, values) -> None:
        self.values = values

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None

    def scalars(self):
        return self

    def all(self):
        return self.values


class QuerySession:
    def __init__(self, values) -> None:
        self.values = values
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return FakeCollectionResult(self.values)


class ControlledAssignmentService(DeviceAssignmentService):
    def __init__(
        self,
        db: FakeSession,
        *,
        device: Device | None,
        asset: Asset,
        active_assignment: DeviceAssetAssignment | None,
        asset_is_available: bool = True,
    ) -> None:
        super().__init__(db)
        self.device = device
        self.asset = asset
        self.active_assignment = active_assignment
        self.asset_is_available = asset_is_available

    async def _get_device_for_update(self, device_id: int) -> Device | None:
        return self.device if self.device and self.device.id_device == device_id else None

    async def _get_assignable_asset(self, device: Device, asset_id: int) -> Asset:
        if asset_id != self.asset.id_asset:
            raise DeviceAssignmentError("Asset not found for this device client.")
        return self.asset

    async def _get_active_assignment_for_update(
        self,
        device_id: int,
    ) -> DeviceAssetAssignment | None:
        return self.active_assignment

    async def _ensure_asset_is_available(
        self,
        asset_id: int,
        device_id: int | None = None,
    ) -> None:
        if not self.asset_is_available:
            raise DeviceAssignmentError("Asset already has a device assigned.")

    @staticmethod
    def _utcnow() -> datetime:
        return ASSIGNMENT_TIME


class DeviceAssetAssignmentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_assignment_updates_current_reference_and_history(self) -> None:
        device = self._device(id_device=1, asset_id=None, active=False)
        asset = self._asset(10)
        session = FakeSession()
        session.track(device, None)
        service = ControlledAssignmentService(
            session,
            device=device,
            asset=asset,
            active_assignment=None,
        )

        result = await service.assign_asset(1, 10)

        assignment = self._added_assignment(session)
        self.assertIs(result, device)
        self.assertEqual(device.asset_id, 10)
        self.assertEqual(assignment.device_id, 1)
        self.assertEqual(assignment.asset_id, 10)
        self.assertEqual(assignment.assigned_at, ASSIGNMENT_TIME)
        self.assertIsNone(assignment.unassigned_at)
        self.assertTrue(session.committed)

    async def test_reassignment_closes_previous_interval_at_new_start(self) -> None:
        device = self._device(id_device=1, asset_id=10, active=True)
        previous = DeviceAssetAssignment(
            device_id=1,
            asset_id=10,
            assigned_at=datetime(2026, 1, 1),
        )
        asset = self._asset(20)
        session = FakeSession()
        session.track(device, previous)
        service = ControlledAssignmentService(
            session,
            device=device,
            asset=asset,
            active_assignment=previous,
        )

        await service.assign_asset(1, 20)

        assignment = self._added_assignment(session)
        self.assertEqual(previous.unassigned_at, ASSIGNMENT_TIME)
        self.assertEqual(assignment.assigned_at, ASSIGNMENT_TIME)
        self.assertEqual(device.asset_id, 20)
        self.assertTrue(device.active)

    async def test_release_closes_history_and_deactivates_device(self) -> None:
        device = self._device(id_device=1, asset_id=10, active=True)
        assignment = DeviceAssetAssignment(
            device_id=1,
            asset_id=10,
            assigned_at=datetime(2026, 1, 1),
        )
        session = FakeSession()
        session.track(device, assignment)
        service = ControlledAssignmentService(
            session,
            device=device,
            asset=self._asset(10),
            active_assignment=assignment,
        )

        result = await service.release_asset(1)

        self.assertIs(result, device)
        self.assertIsNone(device.asset_id)
        self.assertFalse(device.active)
        self.assertEqual(device.state, DeviceState.OFF)
        self.assertEqual(assignment.unassigned_at, ASSIGNMENT_TIME)

    async def test_same_asset_is_idempotent(self) -> None:
        device = self._device(id_device=1, asset_id=10, active=True)
        assignment = DeviceAssetAssignment(
            device_id=1,
            asset_id=10,
            assigned_at=datetime(2026, 1, 1),
        )
        session = FakeSession()
        session.track(device, assignment)
        service = ControlledAssignmentService(
            session,
            device=device,
            asset=self._asset(10),
            active_assignment=assignment,
        )

        result = await service.assign_asset(1, 10)

        self.assertIs(result, device)
        self.assertEqual(session.added, [])
        self.assertFalse(session.committed)
        self.assertIsNone(assignment.unassigned_at)

    async def test_release_without_asset_is_idempotent(self) -> None:
        device = self._device(id_device=1, asset_id=None, active=False)
        session = FakeSession()
        session.track(device, None)
        service = ControlledAssignmentService(
            session,
            device=device,
            asset=self._asset(10),
            active_assignment=None,
        )

        result = await service.release_asset(1)

        self.assertIs(result, device)
        self.assertEqual(session.added, [])
        self.assertFalse(session.committed)

    async def test_reassignment_rolls_back_current_and_historical_changes(self) -> None:
        device = self._device(id_device=1, asset_id=10, active=True)
        previous = DeviceAssetAssignment(
            device_id=1,
            asset_id=10,
            assigned_at=datetime(2026, 1, 1),
        )
        session = FakeSession(commit_error=RuntimeError("database unavailable"))
        session.track(device, previous)
        service = ControlledAssignmentService(
            session,
            device=device,
            asset=self._asset(20),
            active_assignment=previous,
        )

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            await service.assign_asset(1, 20)

        self.assertTrue(session.rolled_back)
        self.assertEqual(device.asset_id, 10)
        self.assertIsNone(previous.unassigned_at)
        self.assertFalse(
            any(
                isinstance(value, DeviceAssetAssignment)
                for value in session.added
            )
        )

    async def test_rejects_asset_assigned_to_another_device(self) -> None:
        device = self._device(id_device=1, asset_id=None, active=False)
        session = FakeSession()
        session.track(device, None)
        service = ControlledAssignmentService(
            session,
            device=device,
            asset=self._asset(10),
            active_assignment=None,
            asset_is_available=False,
        )

        with self.assertRaisesRegex(DeviceAssignmentError, "already has a device"):
            await service.assign_asset(1, 10)

    async def test_create_initial_assignment_persists_device_and_history_together(self) -> None:
        device = self._device(id_device=None, asset_id=None, active=True)
        asset = self._asset(10)
        session = FakeSession()
        session.track(device, None)
        service = ControlledAssignmentService(
            session,
            device=None,
            asset=asset,
            active_assignment=None,
        )

        result = await service.create_initial_assignment(device, asset)

        assignment = self._added_assignment(session)
        self.assertIs(result, device)
        self.assertEqual(device.id_device, 100)
        self.assertEqual(device.asset_id, 10)
        self.assertEqual(assignment.device_id, 100)
        self.assertEqual(assignment.assigned_at, ASSIGNMENT_TIME)

    async def test_historical_asset_query_uses_half_open_range_filters(self) -> None:
        assignments = [
            DeviceAssetAssignment(
                device_id=15,
                asset_id=183,
                assigned_at=datetime(2026, 1, 1),
                unassigned_at=datetime(2026, 5, 20),
            ),
            DeviceAssetAssignment(
                device_id=27,
                asset_id=183,
                assigned_at=datetime(2026, 5, 20),
            ),
        ]
        session = QuerySession(assignments)
        service = DeviceAssignmentService(session)

        result = await service.get_asset_device_assignments(
            183,
            date_from=datetime(2026, 3, 1),
            date_to=datetime(2026, 8, 1),
        )

        statement = str(session.statement)
        self.assertEqual(result, assignments)
        self.assertIn("assigned_at <", statement)
        self.assertIn("unassigned_at >", statement)

    async def test_timestamp_query_excludes_assignment_at_its_end(self) -> None:
        assignment = DeviceAssetAssignment(
            device_id=15,
            asset_id=183,
            assigned_at=datetime(2026, 1, 1),
            unassigned_at=datetime(2026, 5, 20),
        )
        session = QuerySession([assignment])
        service = DeviceAssignmentService(session)

        result = await service.get_assignment_for_device_at(
            15,
            datetime(2026, 5, 20),
        )

        statement = str(session.statement)
        self.assertIs(result, assignment)
        self.assertIn("unassigned_at >", statement)

    async def test_historical_range_requires_valid_half_open_bounds(self) -> None:
        service = DeviceAssignmentService(QuerySession([]))

        with self.assertRaisesRegex(DeviceAssignmentError, "date_from"):
            await service.get_asset_device_assignments(
                183,
                date_from=datetime(2026, 8, 1),
                date_to=datetime(2026, 8, 1),
            )

    def test_history_model_declares_one_active_assignment_per_side(self) -> None:
        indexes = {index.name: index for index in DeviceAssetAssignment.__table__.indexes}

        self.assertTrue(indexes["uq_device_asset_assignments_device_active"].unique)
        self.assertTrue(indexes["uq_device_asset_assignments_asset_active"].unique)

    def _device(
        self,
        *,
        id_device: int | None,
        asset_id: int | None,
        active: bool,
    ) -> Device:
        return Device(
            id_device=id_device,
            serial="COLLAR-001",
            name="Collar 001",
            type="COLLAR",
            client_id=1,
            asset_id=asset_id,
            active=active,
            state=DeviceState.ON,
            deleted="N",
        )

    def _asset(self, asset_id: int) -> Asset:
        return Asset(
            id_asset=asset_id,
            asset_type="CATTLE",
            serial=f"COW-{asset_id:03d}",
            client_id=1,
            status=AssetStatus.ACTIVE,
            deleted="N",
        )

    def _added_assignment(self, session: FakeSession) -> DeviceAssetAssignment:
        return next(
            value
            for value in session.added
            if isinstance(value, DeviceAssetAssignment)
        )


if __name__ == "__main__":
    unittest.main()
