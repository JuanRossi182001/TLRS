from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DeviceCommandAckStatus(Enum):
    EXECUTED = "EXECUTED"
    DUPLICATE = "DUPLICATE"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class DeviceCommandAckPayload(BaseModel):
    command_id: str = Field(min_length=1)
    status: DeviceCommandAckStatus
    executed_at: datetime | None = None
    error_message: str | None = None
