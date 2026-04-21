from db.config.config import sessionlocal

def get_db():
    try:
        db = sessionlocal()
        yield db
    finally:
        db.close()