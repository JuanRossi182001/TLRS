from src.db.config.config import base
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

class User(base):
    """
    Represents the customer or company user/login credentials.
    """

    __tablename__ = "users"

    id_user = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=False, unique=True)
    password = Column(String, nullable=False)
    deleted = Column(String(1), default="N", nullable=False)
    id_client = Column(Integer, ForeignKey("clients.id_client"), nullable=True)
    is_admin=Column(Boolean, default=False, nullable=False)

    user_roles = relationship("UserRoles", back_populates="user")


class Role(base):
    __tablename__ = "roles"

    id_role = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    deleted = Column(String(1), default="N", nullable=False)

    user_roles = relationship("UserRoles", back_populates="role")
    service_roles = relationship("ServiceRoles", back_populates="role")


class UserRoles(base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )

    id_user_role = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id_user"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id_role"), nullable=False)
    deleted = Column(String(1), default="N", nullable=False)

    user = relationship("User", back_populates="user_roles")
    role = relationship("Role", back_populates="user_roles")
