from src.db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy import Enum as SqlAlchemyEnum
from enum import Enum
from sqlalchemy.orm import Mapped,relationship

class AssetStatus(Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Asset(base):
    """
    Represents the tracked business entity.
    Example: tractor, truck, animal, worker, etc.
    """

    __tablename__ = "assets"

    id_asset = Column(Integer, primary_key=True)
    asset_type = Column(String, nullable=False)
    serial = Column(String, unique=True, nullable=False)
    deleted = Column(String(1), default="N", nullable=False)

    client_id = Column(Integer, ForeignKey("clients.id_client"), nullable=True)

    status: Mapped[AssetStatus] = Column(
        SqlAlchemyEnum(AssetStatus),
        default=AssetStatus.ACTIVE,
        nullable=False,
    )

    client = relationship("Client", back_populates="assets")
    devices = relationship("Device", back_populates="asset")
    asset_group_members = relationship("AssetGroupMember", back_populates="asset")
