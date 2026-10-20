import pytest

from src.integrations.chirpstack.api_client import (
    ChirpStackAlreadyExistsError,
    ChirpStackDeviceKeysRecord,
    ChirpStackDeviceRecord,
    ChirpStackNotFoundError,
    ChirpStackValidationError,
)
from src.models.device import (
    Device,
    DeviceCommunicationProtocol,
    DeviceProvisioningStatus,
    DeviceState,
)
from src.models.asset import Asset
from src.schemas.device import ProvisioningAssetCreate
from src.service.device_provisioning_service import (
    DeviceProvisioningConflictError,
    DeviceProvisioningError,
    DeviceProvisioningService,
)


def _provisioning_asset() -> ProvisioningAssetCreate:
    return ProvisioningAssetCreate(asset_type="CATTLE", serial="COW-001")


class FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.commit_count = 0
        self.next_device_id = 1
        self.last_device: Device | None = None

    def add(self, value) -> None:
        self.added.append(value)
        if isinstance(value, Device):
            self.last_device = value

    async def commit(self) -> None:
        self.commit_count += 1
        for value in self.added:
            if isinstance(value, Device) and value.id_device is None:
                value.id_device = self.next_device_id
                self.next_device_id += 1
            if isinstance(value, Device) and not getattr(value, "deleted", None):
                value.deleted = "N"

    async def refresh(self, value) -> None:
        return None

    async def flush(self) -> None:
        for value in self.added:
            if isinstance(value, Asset) and value.id_asset is None:
                value.id_asset = 1
            if isinstance(value, Device) and value.id_device is None:
                value.id_device = self.next_device_id
                self.next_device_id += 1

    async def rollback(self) -> None:
        return None

    async def execute(self, statement):
        if "FROM clients" in str(statement):
            return FakeScalarResult(1)
        return FakeScalarResult(None)


class FakeScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeChirpStackApiClient:
    def __init__(self) -> None:
        self.create_device_calls = []
        self.update_device_calls = []
        self.create_device_keys_calls = []
        self.update_device_keys_calls = []
        self.get_device_calls = []
        self.get_device_keys_calls = []
        self.create_device_exception = None
        self.update_device_exception = None
        self.get_device_exception = None
        self.create_device_keys_exception = None
        self.update_device_keys_exception = None
        self.get_device_keys_exception = None
        self.get_device_response = ChirpStackDeviceRecord(
            dev_eui="0102030405060708",
            name="Collar 001",
            application_id="app-1",
            device_profile_id="profile-1",
            description=None,
            join_eui="1020304050607080",
            is_disabled=False,
            tags={"serial": "COLLAR-001"},
        )
        self.get_device_keys_response = ChirpStackDeviceKeysRecord(
            dev_eui="0102030405060708",
            nwk_key="00112233445566778899aabbccddeeff",
            app_key=None,
        )

    def create_device(self, **kwargs) -> None:
        self.create_device_calls.append(kwargs)
        if self.create_device_exception is not None:
            raise self.create_device_exception

    def update_device(self, **kwargs) -> None:
        self.update_device_calls.append(kwargs)
        if self.update_device_exception is not None:
            raise self.update_device_exception

    def get_device(self, dev_eui: str) -> ChirpStackDeviceRecord:
        self.get_device_calls.append(dev_eui)
        if self.get_device_exception is not None:
            raise self.get_device_exception
        return self.get_device_response

    def create_device_keys(self, **kwargs) -> None:
        self.create_device_keys_calls.append(kwargs)
        if self.create_device_keys_exception is not None:
            raise self.create_device_keys_exception

    def update_device_keys(self, **kwargs) -> None:
        self.update_device_keys_calls.append(kwargs)
        if self.update_device_keys_exception is not None:
            raise self.update_device_keys_exception

    def get_device_keys(self, dev_eui: str) -> ChirpStackDeviceKeysRecord:
        self.get_device_keys_calls.append(dev_eui)
        if self.get_device_keys_exception is not None:
            raise self.get_device_keys_exception
        return self.get_device_keys_response


class StubDeviceProvisioningService(DeviceProvisioningService):
    def __init__(self, db, chirpstack_api_client, devices_by_id: dict[int, Device]):
        super().__init__(db, chirpstack_api_client)
        self.devices_by_id = devices_by_id

    async def _get_device(self, device_id: int) -> Device | None:
        return self.devices_by_id.get(device_id)


@pytest.fixture
def provisioning_context():
    session = FakeSession()
    api_client = FakeChirpStackApiClient()
    return session, api_client, DeviceProvisioningService(session, api_client)


@pytest.fixture
def provisioning_request() -> dict[str, object]:
    return {
        "serial": "COLLAR-001",
        "name": "Collar 001",
        "type": "COLLAR",
        "dev_eui": "0102030405060708",
        "join_eui": "1020304050607080",
        "app_key": "00112233445566778899aabbccddeeff",
        "chirpstack_application_id": "app-1",
        "chirpstack_device_profile_id": "profile-1",
        "client_id": 1,
        "asset": _provisioning_asset(),
    }


def build_device(status: str = DeviceProvisioningStatus.FAILED.value) -> Device:
    return Device(
        id_device=26,
        serial="COLLAR-001",
        name="Collar 001",
        type="COLLAR",
        active=True,
        deleted="N",
        state=DeviceState.OFF,
        communication_protocol=DeviceCommunicationProtocol.CHIRPSTACK,
        chirpstack_dev_eui="0102030405060708",
        join_eui="1020304050607080",
        chirpstack_application_id="app-1",
        chirpstack_device_profile_id="profile-1",
        provisioning_status=status,
        provisioning_error=(
            "previous failure"
            if status == DeviceProvisioningStatus.FAILED.value
            else None
        ),
    )


@pytest.mark.anyio
async def test_provision_device_happy_path(
    provisioning_context,
    provisioning_request: dict[str, object],
) -> None:
    session, api_client, service = provisioning_context

    result = await service.provision_device(**provisioning_request)

    assert len(api_client.create_device_calls) == 1
    assert len(api_client.create_device_keys_calls) == 1
    assert result.provisioning_status == DeviceProvisioningStatus.PROVISIONED
    assert result.app_key_last4 == "eeff"
    assert session.last_device.provisioning_status == DeviceProvisioningStatus.PROVISIONED.value
    assert session.last_device.app_key_last4 == "eeff"
    assert not hasattr(session.last_device, "app_key")


@pytest.mark.anyio
async def test_provision_device_already_exists_compatible_continues(
    provisioning_context,
    provisioning_request: dict[str, object],
) -> None:
    _, api_client, service = provisioning_context
    api_client.create_device_exception = ChirpStackAlreadyExistsError("device exists")

    result = await service.provision_device(**provisioning_request)

    assert result.provisioning_status == DeviceProvisioningStatus.PROVISIONED
    assert len(api_client.get_device_calls) == 1
    assert len(api_client.update_device_calls) == 1


@pytest.mark.anyio
async def test_provision_device_already_exists_incompatible_marks_failed(
    provisioning_context,
    provisioning_request: dict[str, object],
) -> None:
    session, api_client, service = provisioning_context
    api_client.create_device_exception = ChirpStackAlreadyExistsError("device exists")
    api_client.get_device_response = ChirpStackDeviceRecord(
        dev_eui="0102030405060708",
        name="Collar 001",
        application_id="other-app",
        device_profile_id="profile-1",
        description=None,
        join_eui="1020304050607080",
        is_disabled=False,
        tags={"serial": "COLLAR-001"},
    )

    with pytest.raises(DeviceProvisioningConflictError):
        await service.provision_device(**provisioning_request)

    assert session.last_device.provisioning_status == DeviceProvisioningStatus.FAILED.value
    assert "different application_id" in session.last_device.provisioning_error


@pytest.mark.anyio
async def test_provision_device_keys_failure_marks_failed(
    provisioning_context,
    provisioning_request: dict[str, object],
) -> None:
    session, api_client, service = provisioning_context
    api_client.create_device_keys_exception = ChirpStackValidationError("COMMAND_BAD_KEYS")

    with pytest.raises(ChirpStackValidationError):
        await service.provision_device(**provisioning_request)

    assert session.last_device.provisioning_status == DeviceProvisioningStatus.FAILED.value
    assert session.last_device.provisioned_at is None


@pytest.mark.anyio
async def test_retry_provisioning_can_complete_failed_device(
    provisioning_context,
) -> None:
    session, api_client, _ = provisioning_context
    api_client.create_device_exception = ChirpStackAlreadyExistsError("device exists")
    device = build_device()
    service = StubDeviceProvisioningService(session, api_client, {26: device})

    result = await service.retry_provisioning(
        device_id=26,
        app_key="00112233445566778899aabbccddeeff",
    )

    assert result.provisioning_status == DeviceProvisioningStatus.PROVISIONED
    assert device.provisioning_status == DeviceProvisioningStatus.PROVISIONED.value
    assert len(api_client.update_device_calls) == 1


@pytest.mark.anyio
async def test_retry_without_app_key_requires_existing_remote_keys(
    provisioning_context,
) -> None:
    session, api_client, _ = provisioning_context
    api_client.get_device_keys_exception = ChirpStackNotFoundError("missing keys")
    device = build_device()
    service = StubDeviceProvisioningService(session, api_client, {26: device})

    with pytest.raises(DeviceProvisioningError, match="app_key is required"):
        await service.retry_provisioning(device_id=26, app_key=None)

    assert device.provisioning_status == DeviceProvisioningStatus.FAILED.value


@pytest.mark.anyio
async def test_logs_and_errors_do_not_expose_app_key(
    provisioning_context,
    provisioning_request: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    session, api_client, service = provisioning_context
    app_key = str(provisioning_request["app_key"])
    api_client.create_device_keys_exception = ChirpStackValidationError(
        f"invalid key {app_key}"
    )

    with (
        caplog.at_level("WARNING", logger="device_provisioning_service"),
        pytest.raises(ChirpStackValidationError),
    ):
        await service.provision_device(**provisioning_request)

    assert app_key not in caplog.text
    assert "[REDACTED]" in caplog.text
    assert app_key not in session.last_device.provisioning_error


@pytest.mark.anyio
async def test_get_provisioning_does_not_return_app_key(
    provisioning_context,
) -> None:
    session, api_client, _ = provisioning_context
    device = build_device(status=DeviceProvisioningStatus.PROVISIONED.value)
    device.app_key_last4 = "eeff"
    service = StubDeviceProvisioningService(session, api_client, {26: device})

    result = await service.get_provisioning(26)

    assert result.app_key_last4 == "eeff"
    assert not hasattr(result, "app_key")
