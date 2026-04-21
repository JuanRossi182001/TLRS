from db.config.config import base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy import Enum as SqlAlchemyEnum
from enum import Enum
from sqlalchemy.orm import Mapped,relationship

class Client(base):
    """
    Represents the client of the service
    
    """

    __tablename__ = "clients"
    
    id_client = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)