
from src.db.config.config import base
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy import Enum as SqlAlchemyEnum
from sqlalchemy.orm import Mapped,relationship
from enum import Enum
from datetime import datetime


class DeviceState(Enum):
    ON = "ON"
    OFF = "OFF"
    
class DeviceCommunicationProtocol(Enum):
    HTTP = "HTTP"
    MQTT = "MQTT"

class MqttProvider(Enum):
    EMQX_CLOUD = "EMQX_CLOUD"
    MOSQUITTO = "MOSQUITTO"
class CredentialStatus(Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"



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
    )

    id_device = Column(Integer, primary_key=True)
    serial = Column(String, nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    deleted = Column(String(1), default="N", nullable=False)
    
    state: Mapped[DeviceState] = Column(
        SqlAlchemyEnum(DeviceState),
        default=DeviceState.OFF,
        nullable=False,
    )

    communication_protocol: Mapped[DeviceCommunicationProtocol] = Column(
        SqlAlchemyEnum(DeviceCommunicationProtocol),
        default=DeviceCommunicationProtocol.HTTP,
        nullable=False,
    )

    client_id = Column(Integer, ForeignKey("clients.id_client"), nullable=True)
    asset_id = Column(Integer, ForeignKey("assets.id_asset"), nullable=True)

    active = Column(Boolean, default=False, nullable=False)

    client = relationship("Client", back_populates="devices")
    asset = relationship("Asset", back_populates="devices")
    device_credentials = relationship(
        "DeviceCredential",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    telemetry_messages = relationship(
        "TelemetryMessage",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    locations = relationship(
        "Location",
        back_populates="device",
        cascade="all, delete-orphan",
    )


class DeviceCredential(base):
    """
    Represents device authentication material.
    """

    __tablename__ = "device_credentials"
    __table_args__ = (
        Index(
            "uq_device_credentials_mqtt_username_active",
            "mqtt_username",
            unique=True,
            postgresql_where=text("deleted = 'N' AND mqtt_username IS NOT NULL"),
        ),
        Index(
            "uq_device_credentials_mqtt_password_hash_active",
            "mqtt_password_hash",
            unique=True,
            postgresql_where=text("deleted = 'N' AND mqtt_password_hash IS NOT NULL"),
        ),
        Index(
            "uq_device_credentials_mqtt_password_encrypted_active",
            "mqtt_password_encrypted",
            unique=True,
            postgresql_where=text("deleted = 'N' AND mqtt_password_encrypted IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=False)

    secret = Column(String, nullable=False)
    
    mqtt_username = Column(String, nullable=True)
    mqtt_password_hash = Column(String, nullable=True)
    mqtt_password_encrypted = Column(String, nullable=True)
    mqtt_provider: Mapped[MqttProvider] = Column(SqlAlchemyEnum(MqttProvider),default=MqttProvider.EMQX_CLOUD, nullable=True)

    location_topic = Column(String, nullable=True)
    status_topic = Column(String, nullable=True)
    heartbeat_topic = Column(String, nullable=True)
    commands_topic = Column(String, nullable=True)
    acks_topic = Column(String, nullable=True)
    
    deleted = Column(String(1), default="N", nullable=False)

    status: Mapped[CredentialStatus] = Column(
        SqlAlchemyEnum(CredentialStatus),
        default=CredentialStatus.ACTIVE,
        nullable=False,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    device = relationship("Device", back_populates="device_credentials")
