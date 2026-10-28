import importlib.util
from pathlib import Path
from types import SimpleNamespace


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/2026_10_27_1200_9a7c4d2e6f10_add_device_qr_token.py"
)


class MigrationBind:
    def __init__(self, device_ids: list[int]) -> None:
        self.pending_ids = device_ids
        self.backfilled: dict[int, str] = {}

    def execute(self, statement, parameters=None):
        statement_text = str(statement)
        if "SELECT id_device" in statement_text:
            batch_size = parameters["batch_size"]
            rows = self.pending_ids[:batch_size]
            return SimpleNamespace(
                all=lambda: [SimpleNamespace(id_device=device_id) for device_id in rows]
            )

        if "UPDATE devices SET qr_token" in statement_text:
            for item in parameters:
                self.backfilled[item["device_id"]] = item["qr_token"]
                self.pending_ids.remove(item["device_id"])
            return None

        raise AssertionError(f"Unexpected migration SQL: {statement_text}")


class MigrationOperations:
    def __init__(self, bind: MigrationBind) -> None:
        self.bind = bind
        self.added_columns = []
        self.created_indexes = []
        self.altered_columns = []

    def add_column(self, table_name, column) -> None:
        self.added_columns.append((table_name, column))

    def get_bind(self):
        return self.bind

    def create_index(self, name, table_name, columns, **kwargs) -> None:
        self.created_indexes.append((name, table_name, columns, kwargs))

    def alter_column(self, table_name, column_name, **kwargs) -> None:
        self.altered_columns.append((table_name, column_name, kwargs))


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "device_qr_token_migration",
        MIGRATION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_backfills_all_devices_and_enforces_unique_non_null_token() -> None:
    module = _load_migration()
    bind = MigrationBind([10, 20, 30])
    operations = MigrationOperations(bind)
    module.op = operations

    module.upgrade()

    tokens = list(bind.backfilled.values())
    assert len(tokens) == 3
    assert len(set(tokens)) == 3
    assert all(len(token) == 43 for token in tokens)
    assert operations.added_columns[0][0] == "devices"
    assert operations.added_columns[0][1].nullable is True
    assert operations.created_indexes[0][0] == "uq_devices_qr_token"
    assert operations.created_indexes[0][3]["unique"] is True
    assert operations.altered_columns[0][1] == "qr_token"
    assert operations.altered_columns[0][2]["nullable"] is False
