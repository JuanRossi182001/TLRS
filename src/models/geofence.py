from datetime import datetime
from enum import Enum
from sqlalchemy import UniqueConstraint
from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SqlAlchemyEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import relationship

from src.db.config.config import base


class GeoFence(base):
    __tablename__ = "geofences"
    __table_args__ = (
        Index("idx_geofences_client_id", "client_id"),
        Index(
            "uq_geofences_client_name_active",
            "client_id",
            "name",
            unique=True,
            postgresql_where=text("deleted = 'N'"),
        ),
    )

    id_geofence = Column(Integer, primary_key=True)

    client_id = Column(
        Integer,
        ForeignKey("clients.id_client"),
        nullable=False,
    )

    name = Column(String, nullable=False)
    description = Column(String, nullable=True)

    shape = Column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326),
        nullable=False,
    )

    active = Column(Boolean, default=True, nullable=False)
    deleted = Column(String(1), default="N", nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    events = relationship(
        "GeoFenceEvent",
        back_populates="geofence",
        cascade="all, delete-orphan",
    )

    assignments = relationship(
        "GeoFenceAssignment",
        back_populates="geofence",
        cascade="all, delete-orphan",
    )


class GeoFenceAssignment(base):
    __tablename__ = "geofence_assignments"
    __table_args__ = (
        Index("idx_geofence_assignments_asset_id", "asset_id"),
        Index("idx_geofence_assignments_fence_id", "fence_id"),
        Index(
            "uq_geofence_assignments_asset_fence_active",
            "asset_id",
            "fence_id",
            unique=True,
            postgresql_where=text("deleted = 'N' AND active = true"),
        ),
    )

    id_assignment = Column(Integer, primary_key=True)

    asset_id = Column(
        Integer,
        ForeignKey("assets.id_asset"),
        nullable=False,
    )

    fence_id = Column(
        Integer,
        ForeignKey("geofences.id_geofence"),
        nullable=False,
    )

    active = Column(Boolean, default=True, nullable=False)
    deleted = Column(String(1), default="N", nullable=False)

    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    unassigned_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    geofence = relationship(
        "GeoFence",
        back_populates="assignments",
    )

    asset = relationship("Asset")


class FenceEventType(Enum):
    NEAR_LIMIT = "NEAR_LIMIT"
    EXITED = "EXITED"
    ENTERED = "ENTERED"
    RETURNED = "RETURNED"
    GPS_UNCERTAIN = "GPS_UNCERTAIN"


class GeoFenceEvent(base):
    __tablename__ = "geofence_events"
    __table_args__ = (
        Index("idx_geofence_events_device_id_created_at", "device_id", "created_at"),
        Index("idx_geofence_events_fence_id_created_at", "fence_id", "created_at"),
        Index("idx_geofence_events_location_id", "location_id"),
    )

    id_event = Column(Integer, primary_key=True)

    fence_id = Column(
        Integer,
        ForeignKey("geofences.id_geofence"),
        nullable=False,
    )

    device_id = Column(
        Integer,
        ForeignKey("devices.id_device"),
        nullable=False,
    )

    asset_id = Column(
        Integer,
        ForeignKey("assets.id_asset"),
        nullable=True,
    )

    location_id = Column(
        Integer,
        ForeignKey("locations.id_location"),
        nullable=False,
    )

    event_type = Column(
        SqlAlchemyEnum(FenceEventType),
        nullable=False,
    )

    distance_to_boundary_meters = Column(Float, nullable=True)
    accuracy = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    geofence = relationship(
        "GeoFence",
        back_populates="events",
    )

    device = relationship("Device")
    asset = relationship("Asset")
    location = relationship("Location")


class GeoFenceStatus(Enum):
    SAFE = "SAFE"
    NEAR_LIMIT = "NEAR_LIMIT"
    OUTSIDE = "OUTSIDE"
    GPS_UNCERTAIN = "GPS_UNCERTAIN"


class GeoFenceAssetState(base):
    __tablename__ = "geofence_asset_states"

    __table_args__ = (
        UniqueConstraint(
            "fence_id",
            "asset_id",
            name="uq_geofence_asset_state_fence_asset",
        ),
    )

    id_state = Column(Integer, primary_key=True)

    fence_id = Column(Integer, ForeignKey("geofences.id_geofence"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id_asset"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=False)

    current_status = Column(SqlAlchemyEnum(GeoFenceStatus), nullable=False)

    last_location_id = Column(Integer, ForeignKey("locations.id_location"), nullable=False)
    last_distance_to_boundary_meters = Column(Float, nullable=True)
    last_accuracy = Column(Float, nullable=True)

    first_detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_evaluated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    geofence = relationship("GeoFence")
    asset = relationship("Asset")
    device = relationship("Device")
    last_location = relationship("Location")
