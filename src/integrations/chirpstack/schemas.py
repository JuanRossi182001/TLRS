from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.device_command_ack import DeviceCommandAckStatus


class ChirpStackDeviceInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    tenantId: str | None = None
    tenantName: str | None = None
    applicationId: str | None = None
    applicationName: str | None = None
    deviceProfileId: str | None = None
    deviceProfileName: str | None = None
    deviceName: str | None = None
    devEui: str
    tags: dict[str, Any] = Field(default_factory=dict)

    @field_validator("devEui")
    @classmethod
    def normalize_dev_eui(cls, value: str) -> str:
        normalized = "".join(value.split()).lower()
        if not normalized:
            raise ValueError("devEui is required")
        return normalized


class ChirpStackRxInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    gatewayId: str | None = None
    rssi: float | None = None
    snr: float | None = None


class ChirpStackUpObject(BaseModel):
    model_config = ConfigDict(extra="allow")

    lat: float | None = None
    lng: float | None = None
    altitude: float | None = None
    accuracy: float | None = None
    battery: float | None = None


class ChirpStackUpEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    deduplicationId: str | None = None
    time: datetime | None = None
    deviceInfo: ChirpStackDeviceInfo
    fPort: int | None = None
    object: ChirpStackUpObject | None = None
    data: str | None = None
    rxInfo: list[ChirpStackRxInfo] = Field(default_factory=list)


class ChirpStackCommandAckObject(BaseModel):
    model_config = ConfigDict(extra="allow")

    command_id: str
    status: DeviceCommandAckStatus
    executed_at: datetime | None = None
    error_message: str | None = None


class ChirpStackCommandAckUpEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    deduplicationId: str | None = None
    time: datetime | None = None
    deviceInfo: ChirpStackDeviceInfo
    fPort: int
    object: ChirpStackCommandAckObject


class ChirpStackTxAckEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    commandId: str | None = None
    queueItemId: str | None = None
    gatewayId: str | None = None
    time: datetime | None = None
    status: str | None = None


class ChirpStackNetworkAckEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    commandId: str | None = None
    queueItemId: str | None = None
    acknowledged: bool | None = None
    time: datetime | None = None
