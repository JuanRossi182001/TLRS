from src.models.device import Device, DeviceCredential
from src.schemas.device import (
    DeviceCreate,
    DeviceCredentialCreate,
    DeviceCredentialUpdate,
    DeviceUpdate,
)
from src.service.crud_base import CrudBase


class DeviceService(CrudBase[Device, DeviceCreate, DeviceUpdate]):
    model = Device


class DeviceCredentialService(
    CrudBase[DeviceCredential, DeviceCredentialCreate, DeviceCredentialUpdate]
):
    model = DeviceCredential

