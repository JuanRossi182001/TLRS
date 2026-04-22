from db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy import Enum as SqlAlchemyEnum
from datetime import datetime
from sqlalchemy.orm import Mapped,relationship
from .device import DeviceCommunicationProtocol

class TelemetryMessage(base):
    """
    Stores the raw incoming telemetry for traceability and debugging.
    """

    __tablename__ = "telemetry_messages"

    id_telemetry = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=False)

    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    raw_payload = Column(Text, nullable=False)

    protocol: Mapped[DeviceCommunicationProtocol] = Column(
        SqlAlchemyEnum(DeviceCommunicationProtocol),
        default=DeviceCommunicationProtocol.HTTP,
        nullable=False,
    )

    source_ip = Column(String, nullable=True)

    device = relationship("Device", back_populates="telemetry_messages")