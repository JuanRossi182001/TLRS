from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from src.models.geofence import GeoFenceStatus
from src.models.device import (
    CredentialStatus,
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
    type: str = Field(min_length=1, max_length=255)
    state: DeviceState = DeviceState.OFF
    communication_protocol: DeviceCommunicationProtocol = DeviceCommunicationProtocol.HTTP
    client_id: int | None = None
    asset_id: int | None = None
    active: bool = False


class DeviceLastLocation(BaseModel):
    id_device: int
    serial: str
    name: str
    type: str
    client_id: int | None = None
    asset_id: int | None = None
    active: bool = False
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

class DeviceRead(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id_device: int
    last_seen_at: datetime | None = None


class DeviceCredentialBase(BaseModel):
    device_id: int
    status: CredentialStatus = CredentialStatus.ACTIVE


class DeviceCredentialCreate(DeviceCredentialBase):
    secret: str = Field(min_length=1, max_length=255)


class DeviceCredentialUpdate(BaseModel):
    secret: Optional[str] =  None
    status: CredentialStatus | None = None
    revoked_at: Optional[datetime] = None


class DeviceCredentialRead(DeviceCredentialBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    revoked_at: datetime | None = None


class DeviceCredentialReadWithSecret(DeviceCredentialRead):
    secret: str


class DeviceCreateSch(BaseModel):
    serial: str
    name: str
    type: str
    client_id: int | None = None
    asset_id: int | None = None


class ProvisionedDeviceSch(BaseModel):
    id_device: int
    serial: str
    name: str
    type: str
    communication_protocol: str
    active: bool


class ProvisioningMqttSch(BaseModel):
    host: str | None
    port: int
    tls_enabled: bool
    username: str
    password: str
    location_topic: str
    status_topic: str
    heartbeat_topic: str


class ProvisioningSecuritySch(BaseModel):
    hmac_secret: str
    algorithm: str = "HMAC-SHA256"


class DeviceProvisioningResponseSch(BaseModel):
    device: ProvisionedDeviceSch
    mqtt: ProvisioningMqttSch
    security: ProvisioningSecuritySch

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
    status: Optional[GeoFenceStatus] = None
