import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/2026_09_02_1200_d2a4f6c8e0b1_add_asset_rbac_service.py"
)


class MigrationBindRecorder:
    def __init__(self) -> None:
        self.executed = []

    def execute(self, statement, parameters) -> None:
        self.executed.append((str(statement), parameters))


class MigrationOperationsRecorder:
    def __init__(self) -> None:
        self.bind = MigrationBindRecorder()

    def get_bind(self) -> MigrationBindRecorder:
        return self.bind


class AssetRbacMigrationTests(unittest.TestCase):
    def test_upgrade_registers_and_assigns_my_assets_permission(self) -> None:
        module = self._load_migration_module()
        operations = MigrationOperationsRecorder()
        module.op = operations

        module.upgrade()

        self.assertEqual(len(operations.bind.executed), 2)
        self.assertIn("INSERT INTO services", operations.bind.executed[0][0])
        self.assertIn("INSERT INTO service_roles", operations.bind.executed[1][0])
        self.assertEqual(
            operations.bind.executed[0][1],
            {"name": "asset:get my assets"},
        )
        self.assertEqual(
            operations.bind.executed[1][1],
            {"name": "asset:get my assets", "role_id": 1},
        )

    @staticmethod
    def _load_migration_module():
        spec = importlib.util.spec_from_file_location(
            "asset_rbac_migration",
            MIGRATION_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
