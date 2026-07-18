from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.infrastructure.redis.client import get_redis_client
from src.schemas.realtime_auth import WebSocketTicketResponse
from src.schemas.user import TokenData
from src.service.crud_user import get_current_user
from src.service.realtime_auth_service import (
    RealtimeAuthForbiddenError,
    RealtimeAuthService,
    RealtimeAuthUnauthorizedError,
    RealtimeAuthUnavailableError,
)


router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/websocket-ticket",
    status_code=status.HTTP_200_OK,
    response_model=WebSocketTicketResponse,
)
async def create_websocket_ticket(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    service = RealtimeAuthService(
        db=db,
        redis_client=get_redis_client(),
    )

    try:
        return await service.issue_ticket(current_user)
    except RealtimeAuthUnauthorizedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )
    except RealtimeAuthForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except RealtimeAuthUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
