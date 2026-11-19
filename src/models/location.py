from src.db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, Index, text
from datetime import datetime
from enum import Enum
from geoalchemy2 import Geography
from sqlalchemy.orm import Mapped,relationship

class Location(base):
    """
    Stores curated and normalized location data extracted from telemetry.
    """

    __tablename__ = "locations"
    __table_args__ = (
        Index(
            "ix_locations_analytics_device_observed",
            "device_id",
            text("COALESCE(device_timestamp, received_at)"),
            "id_location",
            postgresql_where=text("deleted = 'N'"),
        ),
        Index(
            "ix_locations_device_latest_received",
            "device_id",
            text("received_at DESC"),
            text("id_location DESC"),
            postgresql_where=text("deleted = 'N'"),
        ),
    )

    id_location = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=False)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    point = Column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    altitude = Column(Float, nullable=True)
    accuracy = Column(Float, nullable=True)

    device_timestamp = Column(DateTime, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Placeholder until you move to PostGIS / geoalchemy
    geometry = Column(String, nullable=True)
    deleted = Column(String(1), default="N", nullable=False)

    device = relationship("Device", back_populates="locations")
