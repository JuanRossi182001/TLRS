import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/2026_08_18_1200_b7c3d5e9f1a2_add_device_asset_assignments.py"
)


class MigrationOperationsRecorder:
    def __init__(self) -> None:
        self.created_tables = []
        self.created_indexes = []
        self.executed = []

    def create_table(self, name, *args, **kwargs) -> None:
        self.created_tables.append(name)

    def create_index(self, name, *args, **kwargs) -> None:
        self.created_indexes.append(name)

    def execute(self, statement) -> None:
        self.executed.append(str(statement))


class DeviceAssetAssignmentMigrationTests(unittest.TestCase):
    def test_backfill_creates_one_active_row_for_current_non_deleted_devices(self) -> None:
        module = self._load_migration_module()
        operations = MigrationOperationsRecorder()
        module.op = operations

        module.upgrade()

        backfill = operations.executed[0]
        self.assertIn("device_asset_assignments", operations.created_tables)
        self.assertIn(
            "uq_device_asset_assignments_device_active",
            operations.created_indexes,
        )
        self.assertIn(
            "uq_device_asset_assignments_asset_active",
            operations.created_indexes,
        )
        self.assertIn("devices.deleted = 'N'", backfill)
        self.assertIn("devices.asset_id IS NOT NULL", backfill)
        self.assertIn(
            "ON CONFLICT (device_id) WHERE unassigned_at IS NULL DO NOTHING",
            backfill,
        )

    @staticmethod
    def _load_migration_module():
        spec = importlib.util.spec_from_file_location(
            "device_asset_assignment_migration",
            MIGRATION_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
