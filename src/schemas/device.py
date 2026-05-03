from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from src.models.device import (
    CredentialStatus,
    DeviceCommunicationProtocol,
    DeviceState,
)


class DeviceBase(BaseModel):
    serial: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=255)
    state: DeviceState = DeviceState.OFF
    communication_protocol: DeviceCommunicationProtocol = DeviceCommunicationProtocol.HTTP
    client_id: int | None = None
    asset_id: int | None = None
    active: bool = False


class DeviceCreate(DeviceBase):
    pass


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
