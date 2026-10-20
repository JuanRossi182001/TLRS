from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class DeviceCommandAckStatus(Enum):
    EXECUTED = "EXECUTED"
    DUPLICATE = "DUPLICATE"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class DeviceCommandAckPayload(BaseModel):
    command_id: str | None = Field(default=None, min_length=1)
    command_seq: int | None = Field(default=None, ge=1, le=65535)
    status: DeviceCommandAckStatus
    executed_at: datetime | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_correlation_fields(self) -> "DeviceCommandAckPayload":
        if self.command_id is None and self.command_seq is None:
            raise ValueError("command_id or command_seq is required")
        return self
