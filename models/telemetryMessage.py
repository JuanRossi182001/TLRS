from db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy import Enum as SqlAlchemyEnum
from enum import Enum
from sqlalchemy.orm import Mapped,relationship
from .device import DeviceComunicationProtocol

class TelemetryMessage(base):
    """
    TelemetryMessage model
    Contains the raw data from the device, device protocol and timestamp
    """
    __tablename__ = "telemetry_messages"
    id_telemetry = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=False)
    recived_at = Column(DateTime, nullable=False)
    raw_payload  = Column(String, nullable=False)
    protocol: Mapped[DeviceComunicationProtocol] = Column(SqlAlchemyEnum(DeviceComunicationProtocol), default=DeviceComunicationProtocol.HTTP, nullable=False)
    source_ip = Column(String, nullable=False)

    device = relationship("Device", back_populates="telemetry_messages")