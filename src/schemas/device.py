from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from src.models.geofence import GeoFenceStatus
from src.models.device import (
    DeviceCommunicationProtocol,
    DeviceState,
)

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

class DeviceRead(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id_device: int
    last_seen_at: datetime | None = None


class DeviceCreateSch(BaseModel):
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
    def normalize_create_chirpstack_dev_eui(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "".join(value.split()).lower()
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
        return self


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
    client_name: str
    asset_name: str
    active: bool
    state: DeviceState
    communication_protocol: DeviceCommunicationProtocol | None = None
    chirpstack_dev_eui: str | None = None
    chirpstack_application_id: str | None = None
    lorawan_class: str | None = None
    chirpstack_device_profile_id: str | None = None
    status: Optional[GeoFenceStatus] = None
