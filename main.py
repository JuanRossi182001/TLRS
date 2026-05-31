import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

import src.models  # noqa: F401 - registers SQLAlchemy models before mapper configuration
from src.application.security.session_cleanup_job import run_user_session_cleanup_job
from src.routers import admin, device, geofence, rbac, telemetry, user
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    session_cleanup_task = asyncio.create_task(run_user_session_cleanup_job())
    try:
        yield
    finally:
        session_cleanup_task.cancel()
        try:
            await session_cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)
app.include_router(rbac.router)
app.include_router(telemetry.router)
app.include_router(device.router)
app.include_router(geofence.router)
app.include_router(user.router)
app.include_router(admin.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Hola Bienvenido a TLRS"}
