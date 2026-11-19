from unittest.mock import patch

import pytest

from src.models.user import Role, User, UserRoles
from src.schemas.user import AdminUserInviteCreate
from src.service.crud_user import UserService


class FakeResult:
    def __init__(self, scalar):
        self.scalar = scalar

    def scalar_one_or_none(self):
        return self.scalar


class FakeAsyncSession:
    def __init__(self, results):
        self.results = list(results)
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement):
        return self.results.pop(0)

    def add(self, instance):
        self.added.append(instance)

    async def flush(self):
        user = next(instance for instance in self.added if isinstance(instance, User))
        user.id_user = 24

    async def commit(self):
        self.commits += 1

    async def refresh(self, instance):
        return None

    async def rollback(self):
        self.rollbacks += 1


@pytest.mark.anyio
async def test_invited_client_user_is_created_with_default_role_atomically():
    role = Role(id_role=5, name="cliente_completo", deleted="N")
    db = FakeAsyncSession([FakeResult(42), FakeResult(role)])
    payload = AdminUserInviteCreate(
        name="client-user",
        email="client@example.com",
        id_client=42,
    )

    with patch("src.service.crud_user.bcryptContext.hash", return_value="hashed-temp"):
        user = await UserService(db).create_invited_user(payload)

    role_assignment = next(
        instance for instance in db.added if isinstance(instance, UserRoles)
    )
    assert user.id_user == 24
    assert role_assignment.user_id == user.id_user
    assert role_assignment.role_id == role.id_role
    assert db.commits == 1
    assert db.rollbacks == 0


@pytest.mark.anyio
async def test_invitation_creation_rolls_back_if_default_role_is_missing():
    db = FakeAsyncSession([FakeResult(42), FakeResult(None)])
    payload = AdminUserInviteCreate(
        name="client-user",
        email="client@example.com",
        id_client=42,
    )

    with pytest.raises(RuntimeError, match="default client role is missing"):
        await UserService(db).create_invited_user(payload)

    assert db.commits == 0
    assert db.rollbacks == 1
