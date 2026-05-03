from src.db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy import Enum as SqlAlchemyEnum
from enum import Enum
from sqlalchemy.orm import Mapped,relationship

class Client(base):
    """
    Represents the customer or company that owns assets/devices.
    """

    __tablename__ = "clients"

    id_client = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    deleted = Column(String(1), default="N", nullable=False)

    devices = relationship("Device", back_populates="client")
    assets = relationship("Asset", back_populates="client")
