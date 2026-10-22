import pytest

from src.service.crud_device import DeviceService


class EmptyMappingsResult:
    def mappings(self):
        return self

    def all(self):
        return []


class StatementCapturingSession:
    statement = None

    async def execute(self, statement):
        self.statement = statement
        return EmptyMappingsResult()


@pytest.mark.anyio
async def test_latest_locations_excludes_devices_without_assigned_asset() -> None:
    session = StatementCapturingSession()

    locations = await DeviceService(session).get_latest_locations_by_client_id(
        client_id=1
    )

    sql = str(session.statement.compile()).lower()
    assert locations == []
    assert "devices.asset_id is not null" in sql
