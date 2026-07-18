import unittest
from datetime import datetime, timedelta

from src.models.user import User, UserSession
from src.service.crud_user import UserService


class FakeResult:
    def __init__(self, *, row=None, scalar=None):
        self._row = row
        self._scalar = scalar

    def one_or_none(self):
        return self._row

    def scalar_one_or_none(self):
        return self._scalar


class FakeAsyncSession:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, stmt):
        if not self.results:
            raise AssertionError("Unexpected execute call.")
        return self.results.pop(0)


class UserRefreshServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rotate_refresh_session_reuses_recent_rotation_during_grace_window(self) -> None:
        now = datetime.utcnow()
        previous_session = UserSession(
            id_session=10,
            user_id=7,
            refresh_token_hash=UserService.hash_refresh_token("old-refresh-token"),
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=30),
            revoked_at=now,
            replaced_by_session_id=11,
            user_agent="test-agent",
            ip_address="127.0.0.1",
            deleted="N",
        )
        replacement_session = UserSession(
            id_session=11,
            user_id=7,
            refresh_token_hash="new-hash",
            issued_at=now,
            expires_at=now + timedelta(days=30),
            revoked_at=None,
            user_agent="test-agent",
            ip_address="127.0.0.1",
            deleted="N",
        )
        user = User(
            id_user=7,
            name="juan",
            email="juan@example.com",
            password="hashed",
            id_client=3,
            is_admin=False,
            deleted="N",
        )
        db = FakeAsyncSession(
            [
                FakeResult(row=None),
                FakeResult(row=(previous_session, user)),
                FakeResult(scalar=replacement_session),
            ]
        )
        service = UserService(db)

        result = await service.rotate_refresh_session(
            refresh_token="old-refresh-token",
            user_agent="test-agent",
            ip_address="127.0.0.1",
        )

        self.assertEqual(result.session.id_session, 11)
        self.assertIsNone(result.refresh_token_pair)
        self.assertEqual(result.token_data.user_id, 7)
        self.assertEqual(result.token_data.client_id, 3)

