import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from src.models.device import (
    DeviceCommunicationProtocol,
    DeviceProvisioningStatus,
    DeviceState,
)
from src.models.asset import AssetStatus
from src.models.geofence import GeoFenceStatus


HEX_16_RE = re.compile(r"^[0-9a-f]{16}$")
HEX_32_RE = re.compile(r"^[0-9a-f]{32}$")


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _hex_error_message(field_name: str, length: int) -> str:
    return f"{field_name} must be a valid {length}-character hex string"

class GeoJSONPoint(BaseModel):
    type: str = "Point"
    coordinates: tuple[float, float]

class DeviceBase(BaseModel):
    id_device: int
    serial: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    asset_name: str
    type: str = Field(min_length=1, max_length=255)
    state: DeviceState = DeviceState.OFF
    communication_protocol: DeviceCommunicationProtocol = DeviceCommunicationProtocol.CHIRPSTACK
    client_id: int | None = None
    asset_id: int | None = None
    active: bool = False
    chirpstack_dev_eui: str | None = None
    chirpstack_application_id: str | None = None
    lorawan_class: str | None = None
    chirpstack_device_profile_id: str | None = None


class DeviceUserStatsResponse(BaseModel):
    total_devices: int
    active_devices: int
    inactive_devices: int
    online_devices: int
    offline_devices: int


class DevicePaginatedResponse(BaseModel):
    total: int
    skip: int
    limit: int
    stats: DeviceUserStatsResponse
    items: list[DeviceBase]


class DeviceLastLocation(BaseModel):
    id_device: int
    serial: str
    name: str
    asset_name: str | None = None
    type: str
    client_id: int | None = None
    asset_id: int | None = None
    active: bool = False
    chirpstack_dev_eui: str | None = None
    chirpstack_application_id: str | None = None
    lorawan_class: str | None = None
    chirpstack_device_profile_id: str | None = None
    id_location: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    point: GeoJSONPoint | None = None
    altitude: float | None = None
    accuracy: float | None = None
    device_timestamp: datetime | None = None
    received_at: datetime | None = None

class DeviceCreate(BaseModel):
    serial: str
    name: str
    type: str
    client_id: int | None = None
    asset_id: int | None = None
    communication_protocol: DeviceCommunicationProtocol = DeviceCommunicationProtocol.CHIRPSTACK
    chirpstack_dev_eui: str | None = None
    chirpstack_application_id: str | None = None
    lorawan_class: str | None = None
    chirpstack_device_profile_id: str | None = None

    @field_validator("chirpstack_dev_eui")
    @classmethod
    def normalize_chirpstack_dev_eui(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "".join(value.split()).lower()
        return normalized or None

    @field_validator("chirpstack_application_id")
    @classmethod
    def normalize_chirpstack_application_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_chirpstack_requirements(self):
        if self.communication_protocol != DeviceCommunicationProtocol.CHIRPSTACK:
            raise ValueError(
                "Only CHIRPSTACK devices can be created through this endpoint"
            )
        if (
            self.communication_protocol == DeviceCommunicationProtocol.CHIRPSTACK
            and not self.chirpstack_dev_eui
        ):
            raise ValueError(
                "chirpstack_dev_eui is required for CHIRPSTACK devices"
            )
        if (
            self.communication_protocol == DeviceCommunicationProtocol.CHIRPSTACK
            and not self.chirpstack_application_id
        ):
            raise ValueError(
                "chirpstack_application_id is required for CHIRPSTACK devices"
            )
        return self

class DeviceUpdate(BaseModel):
    serial: Optional[str] =  None 
    name: Optional[str] =  None 
    type: Optional[str] =  None 
    state: Optional[DeviceState] = None
    communication_protocol: Optional[DeviceCommunicationProtocol] = None
    client_id: Optional[int] =  None 
    asset_id: Optional[int] =  None 
    active: Optional[bool] =  None 
    last_seen_at: datetime | None = None
    chirpstack_dev_eui: str | None = None
    chirpstack_application_id: str | None = None
    lorawan_class: str | None = None
    chirpstack_device_profile_id: str | None = None

    @field_validator("chirpstack_dev_eui")
    @classmethod
    def normalize_updated_chirpstack_dev_eui(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "".join(value.split()).lower()
        return normalized or None

    @field_validator("chirpstack_application_id")
    @classmethod
    def normalize_updated_chirpstack_application_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

class DeviceRead(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id_device: int
    last_seen_at: datetime | None = None


class ProvisioningAssetCreate(BaseModel):
    asset_type: str = Field(min_length=1, max_length=255)
    serial: str = Field(min_length=1, max_length=255)
    status: AssetStatus = AssetStatus.ACTIVE


class ChirpStackDeviceCreate(BaseModel):
    serial: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=255)
    client_id: int = Field(gt=0)
    asset_id: int | None = None
    asset: ProvisioningAssetCreate | None = None
    communication_protocol: DeviceCommunicationProtocol = DeviceCommunicationProtocol.CHIRPSTACK
    dev_eui: str
    join_eui: str
    app_key: str
    chirpstack_application_id: str | None = None
    chirpstack_device_profile_id: str | None = None
    description: str | None = None
    is_disabled: bool = False

    @field_validator("dev_eui")
    @classmethod
    def normalize_dev_eui(cls, value: str) -> str:
        normalized = "".join(value.split()).lower()
        if not normalized:
            raise ValueError("dev_eui is required")
        if not HEX_16_RE.fullmatch(normalized):
            raise ValueError(_hex_error_message("dev_eui", 16))
        return normalized

    @field_validator("join_eui")
    @classmethod
    def normalize_join_eui(cls, value: str) -> str:
        normalized = "".join(value.split()).lower()
        if not normalized:
            raise ValueError("join_eui is required")
        if not HEX_16_RE.fullmatch(normalized):
            raise ValueError(_hex_error_message("join_eui", 16))
        return normalized

    @field_validator("app_key")
    @classmethod
    def normalize_app_key(cls, value: str) -> str:
        normalized = "".join(value.split()).lower()
        if not normalized:
            raise ValueError("app_key is required")
        if not HEX_32_RE.fullmatch(normalized):
            raise ValueError(_hex_error_message("app_key", 32))
        return normalized

    @field_validator("chirpstack_application_id")
    @classmethod
    def normalize_application_id(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("chirpstack_device_profile_id")
    @classmethod
    def normalize_device_profile_id(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_chirpstack_requirements(self):
        if self.communication_protocol != DeviceCommunicationProtocol.CHIRPSTACK:
            raise ValueError(
                "Only CHIRPSTACK devices can be created through this endpoint"
            )
        if (
            self.communication_protocol == DeviceCommunicationProtocol.CHIRPSTACK
            and not self.chirpstack_application_id
        ):
            raise ValueError(
                "chirpstack_application_id is required for CHIRPSTACK devices"
            )
        if (
            self.communication_protocol == DeviceCommunicationProtocol.CHIRPSTACK
            and not self.chirpstack_device_profile_id
        ):
            raise ValueError(
                "chirpstack_device_profile_id is required for CHIRPSTACK devices"
            )
        if (self.asset_id is None) == (self.asset is None):
            raise ValueError("Exactly one of asset_id or asset is required")
        return self


class DeviceAssetAssignmentRequest(BaseModel):
    asset_id: int = Field(gt=0)


class DeviceAssetAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_device: int
    asset_id: int | None
    active: bool
    state: DeviceState


class DeviceCreateSch(ChirpStackDeviceCreate):
    pass


class ProvisionedDeviceSch(BaseModel):
    id_device: int
    serial: str
    name: str
    type: str
    communication_protocol: str
    active: bool
    chirpstack_dev_eui: str | None = None
    chirpstack_application_id: str | None = None
    lorawan_class: str | None = None
    chirpstack_device_profile_id: str | None = None


class DeviceProvisioningResponseSch(BaseModel):
    device: ProvisionedDeviceSch


class ChirpStackRetryProvisioningRequest(BaseModel):
    app_key: str | None = None

    @field_validator("app_key")
    @classmethod
    def normalize_retry_app_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "".join(value.split()).lower()
        if not normalized:
            return None
        if not HEX_32_RE.fullmatch(normalized):
            raise ValueError(_hex_error_message("app_key", 32))
        return normalized


class ChirpStackProvisioningRead(BaseModel):
    id_device: int
    serial: str
    dev_eui: str | None = None
    join_eui: str | None = None
    chirpstack_application_id: str | None = None
    chirpstack_device_profile_id: str | None = None
    provisioning_status: DeviceProvisioningStatus
    provisioned_at: datetime | None = None
    provisioning_error: str | None = None
    app_key_last4: str | None = None

class DevicesStatsAdminResult(BaseModel):
    all_devices: int
    active_devices: int
    inactive_devices: int
    online_devices: int
    offline_devices: int

class DeviceAdminResponse(BaseModel):
    id_device: int
    serial: str
    name: str
    client_id: int | None = None
    client_name: str | None = None
    asset_id: int | None = None
    asset_name: str | None = None
    active: bool
    state: DeviceState
    communication_protocol: DeviceCommunicationProtocol | None = None
    chirpstack_dev_eui: str | None = None
    chirpstack_application_id: str | None = None
    lorawan_class: str | None = None
    chirpstack_device_profile_id: str | None = None
    status: Optional[GeoFenceStatus] = None
