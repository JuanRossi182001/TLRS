import hashlib
import secrets
from datetime import datetime

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User, UserSession
from src.schemas.realtime_auth import (
    RealtimeConnectionScope,
    StoredWebSocketTicket,
    WebSocketTicketResponse,
)
from src.schemas.user import TokenData
from src.settings import settings
from src.utils.validations import validate_user_service_access


class RealtimeAuthError(Exception):
    pass


class RealtimeAuthUnauthorizedError(RealtimeAuthError):
    pass


class RealtimeAuthForbiddenError(RealtimeAuthError):
    pass


class RealtimeAuthUnavailableError(RealtimeAuthError):
    pass


class RealtimeAuthService:
    REALTIME_SERVICE_NAME = "device:get latest locations"
    WS_TICKET_KEY_PREFIX = "manea:ws-ticket"

    def __init__(self, db: AsyncSession, redis_client: Redis):
        self.db = db
        self.redis_client = redis_client

    async def issue_ticket(
        self,
        current_user: TokenData,
    ) -> WebSocketTicketResponse:
        if current_user.session_id is None:
            raise RealtimeAuthUnauthorizedError("Realtime authentication failed.")

        access_scope = await self._resolve_realtime_access(
            user_id=current_user.user_id,
            session_id=current_user.session_id,
        )
        ticket = secrets.token_urlsafe(48)
        ticket_key = self.build_ticket_key(ticket)
        payload = StoredWebSocketTicket(
            user_id=access_scope.user_id,
            session_id=access_scope.session_id,
        )

        try:
            await self.redis_client.set(
                ticket_key,
                payload.model_dump_json(),
                ex=settings.websocket_ticket_ttl_seconds,
            )
        except RedisError as exc:
            raise RealtimeAuthUnavailableError(
                "Realtime authentication is unavailable."
            ) from exc

        return WebSocketTicketResponse(
            ticket=ticket,
            expires_in=settings.websocket_ticket_ttl_seconds,
        )

    async def consume_ticket(
        self,
        ticket: str | None,
    ) -> RealtimeConnectionScope:
        if ticket is None or not ticket.strip():
            raise RealtimeAuthUnauthorizedError("Realtime authentication failed.")

        try:
            payload_json = await self.redis_client.getdel(
                self.build_ticket_key(ticket)
            )
        except RedisError as exc:
            raise RealtimeAuthUnavailableError(
                "Realtime authentication is unavailable."
            ) from exc

        if payload_json is None:
            raise RealtimeAuthUnauthorizedError("Realtime authentication failed.")

        try:
            payload = StoredWebSocketTicket.model_validate_json(payload_json)
        except ValueError as exc:
            raise RealtimeAuthUnauthorizedError("Realtime authentication failed.") from exc

        return await self._resolve_realtime_access(
            user_id=payload.user_id,
            session_id=payload.session_id,
        )

    def validate_origin(self, origin: str | None) -> None:
        allowed_origins = settings.cors_allowed_origins_list
        if "*" in allowed_origins:
            return

        if origin is None or origin not in allowed_origins:
            raise RealtimeAuthForbiddenError("Realtime origin is not allowed.")

    def build_ticket_key(self, ticket: str) -> str:
        return f"{self.WS_TICKET_KEY_PREFIX}:{self.hash_ticket(ticket)}"

    @staticmethod
    def hash_ticket(ticket: str) -> str:
        return hashlib.sha256(ticket.encode("utf-8")).hexdigest()

    async def _resolve_realtime_access(
        self,
        *,
        user_id: int,
        session_id: int,
    ) -> RealtimeConnectionScope:
        user_session_row = await self._get_active_user_session(
            user_id=user_id,
            session_id=session_id,
        )
        if user_session_row is None:
            raise RealtimeAuthUnauthorizedError("Realtime authentication failed.")

        user, session = user_session_row
        current_user = TokenData(
            user_id=user.id_user,
            username=user.name,
            client_id=user.id_client,
            is_admin=user.is_admin,
            session_id=session.id_session,
        )

        try:
            await validate_user_service_access(
                current_user,
                self.REALTIME_SERVICE_NAME,
                self.db,
            )
        except HTTPException as exc:
            if exc.status_code in {
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            }:
                raise RealtimeAuthForbiddenError(
                    "Realtime access is not allowed."
                ) from exc
            raise

        if user.id_client is None:
            raise RealtimeAuthForbiddenError("Realtime access is not allowed.")

        return RealtimeConnectionScope(
            user_id=user.id_user,
            session_id=session.id_session,
            client_id=user.id_client,
            is_admin=user.is_admin,
        )

    async def _get_active_user_session(
        self,
        *,
        user_id: int,
        session_id: int,
    ) -> tuple[User, UserSession] | None:
        now = datetime.utcnow()
        result = await self.db.execute(
            select(User, UserSession)
            .join(UserSession, UserSession.user_id == User.id_user)
            .where(
                User.id_user == user_id,
                User.deleted == "N",
                UserSession.id_session == session_id,
                UserSession.user_id == user_id,
                UserSession.deleted == "N",
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
        )
        return result.one_or_none()
