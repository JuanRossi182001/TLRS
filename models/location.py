from db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy import Enum as SqlAlchemyEnum
from enum import Enum
from sqlalchemy.orm import Mapped,relationship

class Location(base):
    """
    Curated and cleaned location data

    """

    __tablename__ = "locations"
    id_location = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=False)
    lat = Column(String, nullable=False)
    long = Column(String, nullable=False)
    altitude = Column(String, nullable=False)
    accuarcy = Column(String, nullable=False)
    geometry = Column(String, nullable=False)


    device = relationship("Device", back_populates="locations")