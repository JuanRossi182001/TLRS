from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.db.config.config import base


class ChirpStackEvent(base):
    __tablename__ = "chirpstack_events"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=True)
    event_type = Column(String, nullable=False)
    application_id = Column(String, nullable=False)
    dev_eui = Column(String, nullable=False)
    deduplication_id = Column(String, nullable=True, unique=True)
    topic = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False)
    processed = Column(Boolean, default=False, nullable=False)
    error_message = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("TIMEZONE('utc', NOW())"),
        nullable=False,
    )

    device = relationship("Device", back_populates="chirpstack_events")
