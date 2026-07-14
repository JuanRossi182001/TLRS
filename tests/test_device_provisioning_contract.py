import unittest

from pydantic import ValidationError

from src.models.device import DeviceCommunicationProtocol
from src.schemas.device import DeviceCreateSch


class DeviceProvisioningContractTests(unittest.TestCase):
    def test_create_device_defaults_to_chirpstack(self) -> None:
        payload = DeviceCreateSch(
            serial="COLLAR-001",
            name="Collar 001",
            type="COLLAR",
            chirpstack_dev_eui="01 02 03 04 05 06 07 08",
        )

        self.assertEqual(
            payload.communication_protocol,
            DeviceCommunicationProtocol.CHIRPSTACK,
        )
        self.assertEqual(payload.chirpstack_dev_eui, "0102030405060708")

    def test_create_device_requires_dev_eui_for_default_chirpstack_flow(self) -> None:
        with self.assertRaises(ValidationError):
            DeviceCreateSch(
                serial="COLLAR-001",
                name="Collar 001",
                type="COLLAR",
            )

    def test_explicit_mqtt_devices_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            DeviceCreateSch(
                serial="MQTT-001",
                name="MQTT 001",
                type="COLLAR",
                communication_protocol=DeviceCommunicationProtocol.MQTT,
            )


if __name__ == "__main__":
    unittest.main()
