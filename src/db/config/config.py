from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from src.settings import settings

DATABASE_URL = settings.sqlalchemy_database_url

engine = create_engine(DATABASE_URL)
sessionlocal = sessionmaker(autocommit = False, autoflush = False, bind = engine)
base = declarative_base()
