import asyncio
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI

import src.models  # noqa: F401 - registers SQLAlchemy models before mapper configuration
from src.application.security.session_cleanup_job import run_user_session_cleanup_job
from src.routers import admin, asset, asset_group, auth, device, geofence, rbac, realtime, user
from fastapi.middleware.cors import CORSMiddleware

from src.infrastructure.redis.client import redis_client, close_redis_client
from src.realtime.locations_suscriber import listen_location_events
from src.realtime.connection_manager import connection_manager
from src.settings import settings

logger = logging.getLogger(__name__)


def _log_background_task_result(task: asyncio.Task, task_name: str) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Background task cancelled during shutdown. task=%s", task_name)
    except Exception:
        logger.exception("Background task crashed. task=%s", task_name)

@asynccontextmanager
async def lifespan(app: FastAPI):
    session_cleanup_task = asyncio.create_task(run_user_session_cleanup_job())
    logger.info("Application realtime services started")

    location_subscriber_task = asyncio.create_task(
        listen_location_events(
            redis_client,
            connection_manager
            ),
        name="redis-location-subscriber",
    )
    session_cleanup_task.add_done_callback(
        lambda task: _log_background_task_result(task, "session-cleanup")
    )
    location_subscriber_task.add_done_callback(
        lambda task: _log_background_task_result(task, "redis-location-subscriber")
    )

    try:
        yield
    finally:
        session_cleanup_task.cancel()
        location_subscriber_task.cancel()

        with suppress(asyncio.CancelledError):
            await location_subscriber_task

        await close_redis_client()
        logger.info("Application realtime services stopped")
        try:
            await session_cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)
app.include_router(rbac.router)
app.include_router(device.router)
app.include_router(asset.router)
app.include_router(asset_group.router)
app.include_router(geofence.router)
app.include_router(auth.router)
app.include_router(user.router)
app.include_router(admin.router)
app.include_router(realtime.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Hola Bienvenido a TLRS"}
