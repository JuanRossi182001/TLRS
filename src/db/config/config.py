from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base

from src.settings import settings

DATABASE_URL = settings.sqlalchemy_database_url
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
ASYNC_DATABASE_URL = ASYNC_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(ASYNC_DATABASE_URL)
sessionlocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)
base = declarative_base()
