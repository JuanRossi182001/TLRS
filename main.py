from fastapi import FastAPI

import src.models  # noqa: F401 - registers SQLAlchemy models before mapper configuration
from src.routers import rbac, telemetry, device, user

app = FastAPI()
app.include_router(rbac.router)
app.include_router(telemetry.router)
app.include_router(device.router)
app.include_router(user.router)
@app.get("/")
async def root():
    return {"message": "Hola Bienvenido a TLRS"}
