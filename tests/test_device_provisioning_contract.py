import unittest

from pydantic import ValidationError

from src.models.device import DeviceCommunicationProtocol
from src.schemas.device import ChirpStackDeviceCreate


class DeviceProvisioningContractTests(unittest.TestCase):
    def test_create_device_defaults_to_chirpstack(self) -> None:
        payload = ChirpStackDeviceCreate(
            serial="COLLAR-001",
            name="Collar 001",
            type="COLLAR",
            client_id=1,
            asset={"asset_type": "CATTLE", "serial": "COW-001"},
            dev_eui="01 02 03 04 05 06 07 08",
            join_eui="10 20 30 40 50 60 70 80",
            app_key="00112233445566778899AABBCCDDEEFF",
            chirpstack_application_id=" app-1 ",
            chirpstack_device_profile_id=" profile-1 ",
        )

        self.assertEqual(
            payload.communication_protocol,
            DeviceCommunicationProtocol.CHIRPSTACK,
        )
        self.assertEqual(payload.dev_eui, "0102030405060708")
        self.assertEqual(payload.join_eui, "1020304050607080")
        self.assertEqual(payload.app_key, "00112233445566778899aabbccddeeff")
        self.assertEqual(payload.chirpstack_application_id, "app-1")

    def test_create_device_requires_dev_eui_for_default_chirpstack_flow(self) -> None:
        with self.assertRaises(ValidationError):
            ChirpStackDeviceCreate(
                serial="COLLAR-001",
                name="Collar 001",
                type="COLLAR",
                client_id=1,
                asset={"asset_type": "CATTLE", "serial": "COW-001"},
                join_eui="1020304050607080",
                app_key="00112233445566778899aabbccddeeff",
                chirpstack_application_id="app-1",
                chirpstack_device_profile_id="profile-1",
            )

    def test_create_device_requires_application_id_for_default_chirpstack_flow(self) -> None:
        with self.assertRaises(ValidationError):
            ChirpStackDeviceCreate(
                serial="COLLAR-001",
                name="Collar 001",
                type="COLLAR",
                client_id=1,
                asset={"asset_type": "CATTLE", "serial": "COW-001"},
                dev_eui="0102030405060708",
                join_eui="1020304050607080",
                app_key="00112233445566778899aabbccddeeff",
                chirpstack_device_profile_id="profile-1",
            )

    def test_create_device_rejects_invalid_dev_eui(self) -> None:
        with self.assertRaises(ValidationError):
            ChirpStackDeviceCreate(
                serial="COLLAR-001",
                name="Collar 001",
                type="COLLAR",
                client_id=1,
                asset={"asset_type": "CATTLE", "serial": "COW-001"},
                dev_eui="invalid",
                join_eui="1020304050607080",
                app_key="00112233445566778899aabbccddeeff",
                chirpstack_application_id="app-1",
                chirpstack_device_profile_id="profile-1",
            )

    def test_create_device_rejects_invalid_app_key(self) -> None:
        with self.assertRaises(ValidationError):
            ChirpStackDeviceCreate(
                serial="COLLAR-001",
                name="Collar 001",
                type="COLLAR",
                client_id=1,
                asset={"asset_type": "CATTLE", "serial": "COW-001"},
                dev_eui="0102030405060708",
                join_eui="1020304050607080",
                app_key="bad-key",
                chirpstack_application_id="app-1",
                chirpstack_device_profile_id="profile-1",
            )

    def test_explicit_mqtt_devices_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ChirpStackDeviceCreate(
                serial="MQTT-001",
                name="MQTT 001",
                type="COLLAR",
                client_id=1,
                asset={"asset_type": "CATTLE", "serial": "COW-001"},
                communication_protocol=DeviceCommunicationProtocol.MQTT,
                dev_eui="0102030405060708",
                join_eui="1020304050607080",
                app_key="00112233445566778899aabbccddeeff",
                chirpstack_application_id="app-1",
                chirpstack_device_profile_id="profile-1",
            )

    def test_create_device_requires_exactly_one_asset_reference(self) -> None:
        base_payload = {
            "serial": "COLLAR-001",
            "name": "Collar 001",
            "type": "COLLAR",
            "client_id": 1,
            "dev_eui": "0102030405060708",
            "join_eui": "1020304050607080",
            "app_key": "00112233445566778899aabbccddeeff",
            "chirpstack_application_id": "app-1",
            "chirpstack_device_profile_id": "profile-1",
        }

        with self.assertRaises(ValidationError):
            ChirpStackDeviceCreate(**base_payload)

        with self.assertRaises(ValidationError):
            ChirpStackDeviceCreate(
                **base_payload,
                asset_id=5,
                asset={"asset_type": "CATTLE", "serial": "COW-001"},
            )


if __name__ == "__main__":
    unittest.main()
