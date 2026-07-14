
from src.db.config.config import base
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy import Enum as SqlAlchemyEnum
from sqlalchemy.orm import Mapped,relationship
from enum import Enum


class DeviceState(Enum):
    ON = "ON"
    OFF = "OFF"
    
class DeviceCommunicationProtocol(Enum):
    HTTP = "HTTP"
    MQTT = "MQTT"
    CHIRPSTACK = "CHIRPSTACK"



class Device(base):
    """
    Represents the physical tracking device.
    Example: ESP32 + GPS module mounted on an asset.
    """

    __tablename__ = "devices"
    __table_args__ = (
        Index(
            "uq_devices_serial_active",
            "serial",
            unique=True,
            postgresql_where=text("deleted = 'N'"),
        ),
        Index(
            "uq_devices_asset_id_active",
            "asset_id",
            unique=True,
            postgresql_where=text("deleted = 'N' AND asset_id IS NOT NULL"),
        ),
        Index(
            "uq_devices_chirpstack_dev_eui_active",
            "chirpstack_dev_eui",
            unique=True,
            postgresql_where=text(
                "deleted = 'N' AND chirpstack_dev_eui IS NOT NULL"
            ),
        ),
    )

    id_device = Column(Integer, primary_key=True)
    serial = Column(String, nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    chirpstack_dev_eui = Column(String, nullable=True)
    chirpstack_application_id = Column(String, nullable=True)
    lorawan_class = Column(String, nullable=True)
    chirpstack_device_profile_id = Column(String, nullable=True)
    deleted = Column(String(1), default="N", nullable=False)
    
    state: Mapped[DeviceState] = Column(
        SqlAlchemyEnum(DeviceState),
        default=DeviceState.OFF,
        nullable=False,
    )

    communication_protocol: Mapped[DeviceCommunicationProtocol] = Column(
        SqlAlchemyEnum(DeviceCommunicationProtocol),
        default=DeviceCommunicationProtocol.CHIRPSTACK,
        nullable=False,
    )

    client_id = Column(Integer, ForeignKey("clients.id_client"), nullable=True)
    asset_id = Column(Integer, ForeignKey("assets.id_asset"), nullable=True)

    active = Column(Boolean, default=False, nullable=False)

    client = relationship("Client", back_populates="devices")
    asset = relationship("Asset", back_populates="devices")
    locations = relationship(
        "Location",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    chirpstack_events = relationship(
        "ChirpStackEvent",
        back_populates="device",
    )
