from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, text
from sqlalchemy.orm import relationship

from src.db.config.config import base


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class DeviceAssetAssignment(base):
    """Historical interval during which a device was assigned to an asset."""

    __tablename__ = "device_asset_assignments"
    __table_args__ = (
        CheckConstraint(
            "unassigned_at IS NULL OR unassigned_at >= assigned_at",
            name="ck_device_asset_assignments_valid_interval",
        ),
        Index(
            "uq_device_asset_assignments_device_active",
            "device_id",
            unique=True,
            postgresql_where=text("unassigned_at IS NULL"),
        ),
        Index(
            "uq_device_asset_assignments_asset_active",
            "asset_id",
            unique=True,
            postgresql_where=text("unassigned_at IS NULL"),
        ),
        Index(
            "idx_device_asset_assignments_device_assigned_at",
            "device_id",
            "assigned_at",
        ),
        Index(
            "idx_device_asset_assignments_asset_assigned_at",
            "asset_id",
            "assigned_at",
        ),
    )

    id_device_asset_assignment = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id_device"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id_asset"), nullable=False)
    assigned_at = Column(DateTime, nullable=False)
    unassigned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    device = relationship("Device", back_populates="asset_assignments")
    asset = relationship("Asset", back_populates="device_assignments")
