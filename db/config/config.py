from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv
import os

load_dotenv('.env')

database_url = os.getenv("DATABASE_URL")

DATABASE_URL = database_url

engine = create_engine(DATABASE_URL)
sessionlocal = sessionmaker(autocommit = False, autoflush = False, bind = engine)
base = declarative_base()