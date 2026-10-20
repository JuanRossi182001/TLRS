import asyncio
import logging

from src.db.config.config import sessionlocal
from src.service.crud_user import UserService
from src.settings import settings


logger = logging.getLogger(__name__)


async def cleanup_user_sessions_once() -> int:
    async with sessionlocal() as db:
        service = UserService(db)
        return await service.delete_stale_sessions(
            retention_days=settings.user_session_cleanup_retention_days,
        )


async def run_user_session_cleanup_job() -> None:
    interval_seconds = settings.user_session_cleanup_interval_hours * 60 * 60

    while True:
        try:
            deleted_count = await cleanup_user_sessions_once()
            if deleted_count:
                logger.info("Deleted %s stale user sessions.", deleted_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("User session cleanup job failed.")

        await asyncio.sleep(interval_seconds)
