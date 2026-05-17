from src.db.config.config import base
from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship


class Service(base):

    __tablename__ = "services"

    id_service = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    deleted = Column(String(1), default="N", nullable=False)

    service_roles = relationship("ServiceRoles", back_populates="service")


class ServiceRoles(base):
    __tablename__ = "service_roles"
    __table_args__ = (
        UniqueConstraint("service_id", "role_id", name="uq_service_roles_service_role"),
    )

    id_service_role = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey("services.id_service"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id_role"), nullable=False)
    deleted = Column(String(1), default="N", nullable=False)

    service = relationship("Service", back_populates="service_roles")
    role = relationship("Role", back_populates="service_roles")
