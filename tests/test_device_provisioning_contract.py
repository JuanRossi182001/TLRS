import pytest
from pydantic import ValidationError

from src.models.device import DeviceCommunicationProtocol
from src.schemas.device import ChirpStackDeviceCreate


@pytest.fixture
def valid_device_payload() -> dict[str, object]:
    """Provide a fresh valid ChirpStack provisioning request for each test."""
    return {
        "serial": "COLLAR-001",
        "name": "Collar 001",
        "type": "COLLAR",
        "client_id": 1,
        "asset": {"asset_type": "CATTLE", "serial": "COW-001"},
        "dev_eui": "0102030405060708",
        "join_eui": "1020304050607080",
        "app_key": "00112233445566778899aabbccddeeff",
        "chirpstack_application_id": "app-1",
        "chirpstack_device_profile_id": "profile-1",
    }


def test_create_device_defaults_to_chirpstack_and_normalizes_credentials(
    valid_device_payload: dict[str, object],
) -> None:
    valid_device_payload.update(
        dev_eui="01 02 03 04 05 06 07 08",
        join_eui="10 20 30 40 50 60 70 80",
        app_key="00112233445566778899AABBCCDDEEFF",
        chirpstack_application_id=" app-1 ",
        chirpstack_device_profile_id=" profile-1 ",
    )

    payload = ChirpStackDeviceCreate(**valid_device_payload)

    assert payload.communication_protocol == DeviceCommunicationProtocol.CHIRPSTACK
    assert payload.dev_eui == "0102030405060708"
    assert payload.join_eui == "1020304050607080"
    assert payload.app_key == "00112233445566778899aabbccddeeff"
    assert payload.chirpstack_application_id == "app-1"


@pytest.mark.parametrize(
    "required_field",
    ["dev_eui", "chirpstack_application_id"],
    ids=["dev-eui", "application-id"],
)
def test_create_device_requires_chirpstack_identity_fields(
    valid_device_payload: dict[str, object],
    required_field: str,
) -> None:
    del valid_device_payload[required_field]

    with pytest.raises(ValidationError):
        ChirpStackDeviceCreate(**valid_device_payload)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        pytest.param("dev_eui", "invalid", id="invalid-dev-eui"),
        pytest.param("app_key", "bad-key", id="invalid-app-key"),
    ],
)
def test_create_device_rejects_invalid_credentials(
    valid_device_payload: dict[str, object],
    field: str,
    invalid_value: str,
) -> None:
    valid_device_payload[field] = invalid_value

    with pytest.raises(ValidationError):
        ChirpStackDeviceCreate(**valid_device_payload)


def test_explicit_mqtt_devices_are_rejected(
    valid_device_payload: dict[str, object],
) -> None:
    valid_device_payload["communication_protocol"] = DeviceCommunicationProtocol.MQTT

    with pytest.raises(ValidationError):
        ChirpStackDeviceCreate(**valid_device_payload)


def test_create_device_requires_exactly_one_asset_reference(
    valid_device_payload: dict[str, object],
) -> None:
    valid_device_payload.pop("asset")
    with pytest.raises(ValidationError):
        ChirpStackDeviceCreate(**valid_device_payload)

    valid_device_payload["asset"] = {"asset_type": "CATTLE", "serial": "COW-001"}
    valid_device_payload["asset_id"] = 5
    with pytest.raises(ValidationError):
        ChirpStackDeviceCreate(**valid_device_payload)
