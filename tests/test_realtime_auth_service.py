import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

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


class RealtimeAuthServiceTests(unittest.IsolatedAsyncioTestCase):
    def _build_user(self, *, client_id: int | None = 4, is_admin: bool = False, deleted: str = "N") -> User:
        return User(
            id_user=15,
            name="juan",
            email="juan@example.com",
            password="hashed",
            id_client=client_id,
            is_admin=is_admin,
            deleted=deleted,
        )

    def _build_session(self, *, expires_in_seconds: int = 300, revoked_at=None, deleted: str = "N") -> UserSession:
        return UserSession(
            id_session=120,
            user_id=15,
            refresh_token_hash="hash",
            issued_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=expires_in_seconds),
            revoked_at=revoked_at,
            deleted=deleted,
        )

    async def test_issue_ticket_stores_namespaced_hashed_key_with_ttl(self) -> None:
        redis_client = FakeRedis()
        service = RealtimeAuthService(
            db=FakeAsyncSession(self._build_user(client_id=4), self._build_session()),
            redis_client=redis_client,
        )

        with patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=AsyncMock(return_value=True),
        ):
            result = await service.issue_ticket(
                TokenData(
                    user_id=15,
                    username="juan",
                    client_id=999,
                    is_admin=False,
                    session_id=120,
                )
            )

        self.assertEqual(result.expires_in, settings.websocket_ticket_ttl_seconds)
        self.assertEqual(len(redis_client.storage), 1)

        stored_key = next(iter(redis_client.storage))
        stored_payload = json.loads(redis_client.storage[stored_key])

        self.assertTrue(
            stored_key.startswith(f"{RealtimeAuthService.WS_TICKET_KEY_PREFIX}:")
        )
        self.assertNotIn(result.ticket, stored_key)
        self.assertEqual(
            stored_key,
            service.build_ticket_key(result.ticket),
        )
        self.assertEqual(
            redis_client.ttl_by_key[stored_key],
            settings.websocket_ticket_ttl_seconds,
        )
        self.assertEqual(
            stored_payload,
            {
                "user_id": 15,
                "session_id": 120,
            },
        )

    async def test_ticket_can_only_be_consumed_once(self) -> None:
        redis_client = FakeRedis()
        service = RealtimeAuthService(
            db=FakeAsyncSession(self._build_user(client_id=4), self._build_session()),
            redis_client=redis_client,
        )

        with patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=AsyncMock(return_value=True),
        ):
            ticket_response = await service.issue_ticket(
                TokenData(
                    user_id=15,
                    username="juan",
                    client_id=4,
                    is_admin=False,
                    session_id=120,
                )
            )
            connection_scope = await service.consume_ticket(ticket_response.ticket)

        self.assertEqual(connection_scope.client_id, 4)

        with patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=AsyncMock(return_value=True),
        ):
            with self.assertRaises(RealtimeAuthUnauthorizedError):
                await service.consume_ticket(ticket_response.ticket)

    async def test_consume_ticket_rejects_missing_or_expired_ticket(self) -> None:
        redis_client = FakeRedis()
        service = RealtimeAuthService(
            db=FakeAsyncSession(self._build_user(client_id=4), self._build_session()),
            redis_client=redis_client,
        )

        with self.assertRaises(RealtimeAuthUnauthorizedError):
            await service.consume_ticket("missing-ticket")

    async def test_issue_ticket_rejects_inactive_user(self) -> None:
        service = RealtimeAuthService(
            db=FakeAsyncSession(self._build_user(deleted="Y"), self._build_session()),
            redis_client=FakeRedis(),
        )

        with self.assertRaises(RealtimeAuthUnauthorizedError):
            await service.issue_ticket(
                TokenData(
                    user_id=15,
                    username="juan",
                    client_id=4,
                    is_admin=False,
                    session_id=120,
                )
            )

    async def test_issue_ticket_rejects_user_without_client_scope(self) -> None:
        service = RealtimeAuthService(
            db=FakeAsyncSession(self._build_user(client_id=None), self._build_session()),
            redis_client=FakeRedis(),
        )

        with patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=AsyncMock(return_value=True),
        ):
            with self.assertRaises(RealtimeAuthForbiddenError):
                await service.issue_ticket(
                    TokenData(
                        user_id=15,
                        username="juan",
                        client_id=999,
                        is_admin=True,
                        session_id=120,
                    )
                )

    async def test_issue_ticket_reuses_real_user_scope_not_token_client_id(self) -> None:
        redis_client = FakeRedis()
        service = RealtimeAuthService(
            db=FakeAsyncSession(self._build_user(client_id=4), self._build_session()),
            redis_client=redis_client,
        )

        with patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=AsyncMock(return_value=True),
        ):
            ticket_response = await service.issue_ticket(
                TokenData(
                    user_id=15,
                    username="juan",
                    client_id=999,
                    is_admin=False,
                    session_id=120,
                )
            )
            connection_scope = await service.consume_ticket(ticket_response.ticket)

        self.assertEqual(connection_scope.client_id, 4)

    async def test_issue_ticket_raises_when_redis_is_unavailable(self) -> None:
        redis_client = FakeRedis()
        redis_client.set_error = RedisError("redis unavailable")
        service = RealtimeAuthService(
            db=FakeAsyncSession(self._build_user(client_id=4), self._build_session()),
            redis_client=redis_client,
        )

        with patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=AsyncMock(return_value=True),
        ):
            with self.assertRaises(RealtimeAuthUnavailableError):
                await service.issue_ticket(
                    TokenData(
                        user_id=15,
                        username="juan",
                        client_id=4,
                        is_admin=False,
                        session_id=120,
                    )
                )

    async def test_consume_ticket_raises_when_redis_is_unavailable(self) -> None:
        redis_client = FakeRedis()
        redis_client.getdel_error = RedisError("redis unavailable")
        service = RealtimeAuthService(
            db=FakeAsyncSession(self._build_user(client_id=4), self._build_session()),
            redis_client=redis_client,
        )

        with self.assertRaises(RealtimeAuthUnavailableError):
            await service.consume_ticket("ticket")

    async def test_issue_ticket_rejects_user_without_realtime_permission(self) -> None:
        service = RealtimeAuthService(
            db=FakeAsyncSession(self._build_user(client_id=4), self._build_session()),
            redis_client=FakeRedis(),
        )

        with patch(
            "src.service.realtime_auth_service.validate_user_service_access",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="forbidden",
                )
            ),
        ):
            with self.assertRaises(RealtimeAuthForbiddenError):
                await service.issue_ticket(
                    TokenData(
                        user_id=15,
                        username="juan",
                        client_id=4,
                        is_admin=False,
                        session_id=120,
                    )
                )


if __name__ == "__main__":
    unittest.main()
