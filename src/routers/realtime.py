import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.infrastructure.redis.client import get_redis_client
from src.realtime.connection_manager import connection_manager
from src.service.realtime_auth_service import (
    RealtimeAuthForbiddenError,
    RealtimeAuthService,
    RealtimeAuthUnauthorizedError,
    RealtimeAuthUnavailableError,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/ws",
    tags=["Realtime"],
)


@router.websocket("/locations")
async def locations_websocket(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> None:
    raw_ticket = websocket.query_params.get("ticket")
    service = RealtimeAuthService(
        db=db,
        redis_client=get_redis_client(),
    )
    realtime_scope = None

    try:
        realtime_scope = await service.consume_ticket(
            raw_ticket
        )
        service.validate_origin(websocket.headers.get("origin"))
    except RealtimeAuthUnavailableError:
        logger.exception(
            "Realtime websocket handshake failed due to infrastructure error."
        )
        await websocket.close(code=1011)
        return
    except (RealtimeAuthUnauthorizedError, RealtimeAuthForbiddenError):
        logger.warning(
            "Realtime websocket handshake rejected. origin=%s",
            websocket.headers.get("origin"),
        )
        await websocket.close(code=1008)
        return

    await websocket.accept()
    await connection_manager.connect(
        client_id=realtime_scope.client_id,
        websocket=websocket,
    )

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(
            client_id=realtime_scope.client_id,
            websocket=websocket,
        )
