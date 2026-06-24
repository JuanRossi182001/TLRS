from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import relationship

from src.db.config.config import base


class AssetGroup(base):
    __tablename__ = "asset_groups"
    __table_args__ = (
        Index("idx_asset_groups_client_id", "client_id"),
        Index(
            "uq_asset_groups_client_name_active",
            "client_id",
            "name",
            unique=True,
            postgresql_where=text("deleted = 'N'"),
        ),
    )

    id_asset_group = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id_client"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    deleted = Column(String(1), default="N", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    client = relationship("Client", back_populates="asset_groups")
    members = relationship(
        "AssetGroupMember",
        back_populates="asset_group",
        cascade="all, delete-orphan",
    )
    geofence_assignments = relationship(
        "GeoFenceAssetGroup",
        back_populates="asset_group",
        cascade="all, delete-orphan",
    )


class AssetGroupMember(base):
    __tablename__ = "asset_group_members"
    __table_args__ = (
        Index("idx_asset_group_members_asset_group_id", "asset_group_id"),
        Index("idx_asset_group_members_asset_id", "asset_id"),
        Index(
            "uq_asset_group_members_group_asset_active",
            "asset_group_id",
            "asset_id",
            unique=True,
            postgresql_where=text("deleted = 'N'"),
        ),
    )

    id_asset_group_member = Column(Integer, primary_key=True)
    asset_group_id = Column(
        Integer,
        ForeignKey("asset_groups.id_asset_group"),
        nullable=False,
    )
    asset_id = Column(Integer, ForeignKey("assets.id_asset"), nullable=False)
    deleted = Column(String(1), default="N", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    asset_group = relationship("AssetGroup", back_populates="members")
    asset = relationship("Asset", back_populates="asset_group_members")


class GeoFenceAssetGroup(base):
    __tablename__ = "geofence_asset_groups"
    __table_args__ = (
        Index("idx_geofence_asset_groups_geofence_id", "geofence_id"),
        Index("idx_geofence_asset_groups_asset_group_id", "asset_group_id"),
        Index(
            "uq_geofence_asset_groups_geofence_group_active",
            "geofence_id",
            "asset_group_id",
            unique=True,
            postgresql_where=text("deleted = 'N' AND active = true"),
        ),
    )

    id_geofence_asset_group = Column(Integer, primary_key=True)
    geofence_id = Column(
        Integer,
        ForeignKey("geofences.id_geofence"),
        nullable=False,
    )
    asset_group_id = Column(
        Integer,
        ForeignKey("asset_groups.id_asset_group"),
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

    geofence = relationship("GeoFence", back_populates="asset_group_assignments")
    asset_group = relationship("AssetGroup", back_populates="geofence_assignments")
