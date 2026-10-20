from src.db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime,Float
from datetime import datetime
from enum import Enum
from geoalchemy2 import Geography
from sqlalchemy.orm import Mapped,relationship

class Location(base):
    """
    Stores curated and normalized location data extracted from telemetry.
    """

    __tablename__ = "locations"

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
