from db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy import Enum as SqlAlchemyEnum
from enum import Enum
from sqlalchemy.orm import Mapped,relationship


class Asset(base):
    """
    Represents the client asset

    example: Tractor, truck, animal, worker etc etc

    """

    __tablename__ = "assets"

    id_asset = Column(Integer, primary_key=True)
    type_aseet = Column(String, nullable=False)
    serial = Column(String, unique=True)
    client_id = Column(Integer, ForeignKey("clients.id_client"), nullable=True)
    status = Column(String(1), nullable=False)


    client = relationship("Client", back_populates="assets")