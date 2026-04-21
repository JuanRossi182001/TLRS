
from db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean
from sqlalchemy import Enum as SqlAlchemyEnum
from sqlalchemy.orm import Mapped,relationship
from enum import Enum


class DeviceState(Enum):
    ON = "ON"
    OFF = "OFF"

class DeviceComunicationProtocol(Enum):
    HTTP = "HTTP"
    MQTT = "MQTT"  

class Device(base):
    """
    Device model 

    """

    __tablename__ = "devices"

    id_device = Column(Integer, primary_key=True)
    serial = Column(String, unique=True)
    name = Column(String)
    type = Column(String)
    state: Mapped[DeviceState] = Column(SqlAlchemyEnum(DeviceState), default=DeviceState.OFF, nullable=False)
    comunication_protocol: Mapped[DeviceComunicationProtocol] = Column(SqlAlchemyEnum(DeviceComunicationProtocol), default=DeviceComunicationProtocol.HTTP, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id_client"), nullable=True)
    asset_id = Column(Integer, ForeignKey("assets.id_asset"), nullable=True)
    active = Column(Boolean, default=False)

    client = relationship("Client", back_populates="devices")
    assets = relationship("Asset", back_populates="devices")

class DeviceCredential(base):
    """
    Device auth information 

    """

    __tablename__="device_credentials"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=False)
    secret = Column(String, nullable=False)
    status = Column(String(1), nullable=False)
    created_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    device = relationship("Device", back_populates="device_credentials")