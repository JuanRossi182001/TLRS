from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlAlchemyEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, relationship

from src.db.config.config import base


class DeviceCommandType(Enum):
    SET_REPORT_INTERVAL = "SET_REPORT_INTERVAL"
    WARNING_SOUND = "WARNING_SOUND"
    VIBRATION = "VIBRATION"
    STOP_CORRECTION = "STOP_CORRECTION"
    EMERGENCY_DISABLE = "EMERGENCY_DISABLE"
    REQUEST_STATUS = "REQUEST_STATUS"


class DeviceCommandStatus(Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ACKED = "ACKED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class DeviceCommand(base):
    __tablename__ = "device_commands"
    __table_args__ = (
        Index("idx_device_commands_status_created_at", "status", "created_at"),
        Index("idx_device_commands_device_id_created_at", "device_id", "created_at"),
        Index("idx_device_commands_device_id_command_seq", "device_id", "command_seq"),
        Index("idx_device_commands_geofence_event_id", "geofence_event_id"),
        Index(
            "idx_device_commands_chirpstack_queue_item_id",
            "chirpstack_queue_item_id",
        ),
        UniqueConstraint(
            "device_id",
            "command_seq",
            name="uq_device_commands_device_id_command_seq",
        ),
        CheckConstraint(
            "command_seq IS NULL OR (command_seq >= 1 AND command_seq <= 65535)",
            name="ck_device_commands_command_seq_uint16",
        ),
    )

    id_command = Column(Integer, primary_key=True)
    command_uuid = Column(String, unique=True, nullable=False)
    chirpstack_queue_item_id = Column(String, nullable=True)
    command_seq = Column(Integer, nullable=True)

    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id_asset"), nullable=True)
    geofence_event_id = Column(
        Integer,
        ForeignKey("geofence_events.id_event"),
        nullable=True,
    )

    command_type: Mapped[DeviceCommandType] = Column(
        SqlAlchemyEnum(DeviceCommandType),
        nullable=False,
    )
    status: Mapped[DeviceCommandStatus] = Column(
        SqlAlchemyEnum(DeviceCommandStatus),
        default=DeviceCommandStatus.PENDING,
        nullable=False,
    )

    topic = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False)
    qos = Column(Integer, default=1, nullable=False)
    retain = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    tx_acked_at = Column(DateTime, nullable=True)
    lorawan_ack_at = Column(DateTime, nullable=True)
    ack_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)

    device = relationship("Device")
    asset = relationship("Asset")
    geofence_event = relationship("GeoFenceEvent")
