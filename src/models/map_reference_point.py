from datetime import datetime
from enum import Enum

from geoalchemy2 import Geography
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum as SqlAlchemyEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from src.db.config.config import base


class MapReferencePointCategory(str, Enum):
    WATER_TROUGH = "WATER_TROUGH"
    CORRAL = "CORRAL"
    SHED = "SHED"
    FEEDING_POINT = "FEEDING_POINT"
    OTHER = "OTHER"


class MapReferencePoint(base):
    __tablename__ = "map_reference_points"
    __table_args__ = (
        CheckConstraint(
            "category IN "
            "('WATER_TROUGH', 'CORRAL', 'SHED', 'FEEDING_POINT', 'OTHER')",
            name="ck_map_reference_points_category",
        ),
        CheckConstraint(
            "(category = 'OTHER' AND other_type IS NOT NULL "
            "AND length(trim(other_type)) > 0) "
            "OR (category <> 'OTHER' AND other_type IS NULL)",
            name="ck_map_reference_points_other_type",
        ),
    )

    id_map_reference_point = Column(Integer, primary_key=True)
    client_id = Column(
        Integer,
        ForeignKey("clients.id_client"),
        nullable=False,
    )
    category = Column(
        SqlAlchemyEnum(
            MapReferencePointCategory,
            name="map_reference_point_category",
            native_enum=False,
            create_constraint=False,
            length=32,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    other_type = Column(String(100), nullable=True)
    name = Column(String(255), nullable=False)
    point = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    note = Column(Text, nullable=True)
    deleted = Column(String(1), default="N", server_default="N", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    client = relationship("Client", back_populates="map_reference_points")
