import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status
from redis.exceptions import RedisError

from src.models.user import User, UserSession
from src.schemas.user import TokenData
from src.service.realtime_auth_service import (
    RealtimeAuthForbiddenError,
    RealtimeAuthService,
    RealtimeAuthUnauthorizedError,
    RealtimeAuthUnavailableError,
)
from src.settings import settings


class FakeResult:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class FakeAsyncSession:
    def __init__(self, user: User | None, session: UserSession | None):
        self.user = user
        self.session = session

    async def execute(self, stmt):
        now = datetime.utcnow()
        row = None

        if (
            self.user is not None
            and self.session is not None
            and self.user.deleted == "N"
            and self.session.deleted == "N"
            and self.session.user_id == self.user.id_user
            and self.session.revoked_at is None
            and self.session.expires_at > now
        ):
            row = (self.user, self.session)

        return FakeResult(row)


class FakeRedis:
    def __init__(self):
        self.storage: dict[str, str] = {}
        self.ttl_by_key: dict[str, int | None] = {}
        self.set_error: Exception | None = None
        self.getdel_error: Exception | None = None

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if self.set_error is not None:
            raise self.set_error

        self.storage[key] = value
        self.ttl_by_key[key] = ex
        return True

    async def getdel(self, key: str) -> str | None:
        if self.getdel_error is not None:
            raise self.getdel_error

        return self.storage.pop(key, None)


def build_user(
    *,
    client_id: int | None = 4,
    is_admin: bool = False,
    deleted: str = "N",
) -> User:
    return User(
        id_user=15,
        name="juan",
        email="juan@example.com",
        password="hashed",
        id_client=client_id,
        is_admin=is_admin,
        deleted=deleted,
    )


def build_session(
    *,
    expires_in_seconds: int = 300,
    revoked_at: datetime | None = None,
    deleted: str = "N",
) -> UserSession:
    now = datetime.utcnow()
    return UserSession(
        id_session=120,
        user_id=15,
        refresh_token_hash="hash",
        issued_at=now,
        expires_at=now + timedelta(seconds=expires_in_seconds),
        revoked_at=revoked_at,
        deleted=deleted,
    )


def build_token(*, client_id: int | None = 4, is_admin: bool = False) -> TokenData:
    return TokenData(
        user_id=15,
        username="juan",
        client_id=client_id,
        is_admin=is_admin,
        session_id=120,
    )


@pytest.fixture
def auth_context() -> tuple[RealtimeAuthService, FakeRedis]:
    """Build fresh service dependencies so ticket state cannot leak between tests."""
    redis_client = FakeRedis()
    service = RealtimeAuthService(
        db=FakeAsyncSession(build_user(), build_session()),
        redis_client=redis_client,
    )
    return service, redis_client


@pytest.mark.anyio
async def test_issue_ticket_stores_namespaced_hashed_key_with_ttl(
    auth_context: tuple[RealtimeAuthService, FakeRedis],
) -> None:
    service, redis_client = auth_context

    with patch(
        "src.service.realtime_auth_service.validate_user_service_access",
        new=AsyncMock(return_value=True),
    ):
        result = await service.issue_ticket(build_token(client_id=999))

    assert result.expires_in == settings.websocket_ticket_ttl_seconds
    assert len(redis_client.storage) == 1

    stored_key = next(iter(redis_client.storage))
    stored_payload = json.loads(redis_client.storage[stored_key])

    assert stored_key.startswith(f"{RealtimeAuthService.WS_TICKET_KEY_PREFIX}:")
    assert result.ticket not in stored_key
    assert stored_key == service.build_ticket_key(result.ticket)
    assert redis_client.ttl_by_key[stored_key] == settings.websocket_ticket_ttl_seconds
    assert stored_payload == {"user_id": 15, "session_id": 120}


@pytest.mark.anyio
async def test_ticket_can_only_be_consumed_once(
    auth_context: tuple[RealtimeAuthService, FakeRedis],
) -> None:
    service, _ = auth_context

    with patch(
        "src.service.realtime_auth_service.validate_user_service_access",
        new=AsyncMock(return_value=True),
    ):
        ticket_response = await service.issue_ticket(build_token())
        connection_scope = await service.consume_ticket(ticket_response.ticket)

    assert connection_scope.client_id == 4

    with pytest.raises(RealtimeAuthUnauthorizedError):
        await service.consume_ticket(ticket_response.ticket)


@pytest.mark.anyio
async def test_consume_ticket_rejects_missing_ticket(
    auth_context: tuple[RealtimeAuthService, FakeRedis],
) -> None:
    service, _ = auth_context

    with pytest.raises(RealtimeAuthUnauthorizedError):
        await service.consume_ticket("missing-ticket")


@pytest.mark.anyio
async def test_issue_ticket_rejects_inactive_user() -> None:
    service = RealtimeAuthService(
        db=FakeAsyncSession(build_user(deleted="Y"), build_session()),
        redis_client=FakeRedis(),
    )

    with pytest.raises(RealtimeAuthUnauthorizedError):
        await service.issue_ticket(build_token())


@pytest.mark.anyio
async def test_issue_ticket_rejects_user_without_client_scope() -> None:
    service = RealtimeAuthService(
        db=FakeAsyncSession(build_user(client_id=None), build_session()),
        redis_client=FakeRedis(),
    )

    with (
        patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=AsyncMock(return_value=True),
        ),
        pytest.raises(RealtimeAuthForbiddenError),
    ):
        await service.issue_ticket(build_token(client_id=999, is_admin=True))


@pytest.mark.anyio
async def test_issue_ticket_reuses_real_user_scope_not_token_client_id(
    auth_context: tuple[RealtimeAuthService, FakeRedis],
) -> None:
    service, _ = auth_context

    with patch(
        "src.service.realtime_auth_service.validate_user_service_access",
        new=AsyncMock(return_value=True),
    ):
        ticket_response = await service.issue_ticket(build_token(client_id=999))
        connection_scope = await service.consume_ticket(ticket_response.ticket)

    assert connection_scope.client_id == 4


@pytest.mark.anyio
async def test_issue_ticket_raises_when_redis_is_unavailable(
    auth_context: tuple[RealtimeAuthService, FakeRedis],
) -> None:
    service, redis_client = auth_context
    redis_client.set_error = RedisError("redis unavailable")

    with (
        patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=AsyncMock(return_value=True),
        ),
        pytest.raises(RealtimeAuthUnavailableError),
    ):
        await service.issue_ticket(build_token())


@pytest.mark.anyio
async def test_consume_ticket_raises_when_redis_is_unavailable(
    auth_context: tuple[RealtimeAuthService, FakeRedis],
) -> None:
    service, redis_client = auth_context
    redis_client.getdel_error = RedisError("redis unavailable")

    with pytest.raises(RealtimeAuthUnavailableError):
        await service.consume_ticket("ticket")


@pytest.mark.anyio
async def test_issue_ticket_rejects_user_without_realtime_permission(
    auth_context: tuple[RealtimeAuthService, FakeRedis],
) -> None:
    service, _ = auth_context
    permission_check = AsyncMock(
        side_effect=HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden",
        )
    )

    with (
        patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=permission_check,
        ),
        pytest.raises(RealtimeAuthForbiddenError),
    ):
        await service.issue_ticket(build_token())
