from sqlalchemy import Column, Index, Integer, String, func, text
from sqlalchemy.orm import relationship

from src.db.config.config import base


class Client(base):
    """
    Represents the customer or company that owns assets/devices.
    """

    __tablename__ = "clients"
    __table_args__ = (
        Index(
            "uq_clients_email_active_ci",
            func.lower(text("email")),
            unique=True,
            postgresql_where=text("deleted = 'N'"),
        ),
    )

    id_client = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    deleted = Column(String(1), default="N", nullable=False)

    devices = relationship("Device", back_populates="client")
    assets = relationship("Asset", back_populates="client")
    asset_groups = relationship("AssetGroup", back_populates="client")
