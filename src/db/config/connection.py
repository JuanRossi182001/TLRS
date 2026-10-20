from src.db.config.config import sessionlocal

async def get_db():
    async with sessionlocal() as db:
        yield db
