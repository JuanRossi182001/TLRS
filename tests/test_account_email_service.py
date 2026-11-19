from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from src.models.user import User, UserEmailToken
from src.schemas.user import PasswordResetRequest
from src.service.account_email_service import (
    ACCOUNT_ACTIVATION,
    AccountEmailService,
    PASSWORD_RESET,
)
from src.service.crud_user import UserService, bcryptContext


class FakeResult:
    def __init__(self, row=None, scalar=None):
        self.row = row
        self.scalar = scalar

    def one_or_none(self):
        return self.row

    def scalar_one_or_none(self):
        return self.scalar


class FakeAsyncSession:
    def __init__(self, results):
        self.results = list(results)
        self.added = []
        self.commits = 0
        self.executed_statements = []

    async def execute(self, statement):
        self.executed_statements.append(statement)
        if self.results:
            return self.results.pop(0)
        return FakeResult()

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1


@pytest.mark.anyio
async def test_password_reset_consumes_token_verifies_email_and_changes_password():
    token = UserEmailToken(
        user_id=9,
        token_hash=AccountEmailService.hash_token("one-time-secret"),
        purpose=PASSWORD_RESET,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        used_at=None,
    )
    user = User(
        id_user=9,
        name="field-user",
        email="field@example.com",
        password="old-password-hash",
        email_verified_at=None,
        email_verification_required=True,
        deleted="N",
    )
    db = FakeAsyncSession([FakeResult(row=(token, user))])

    await AccountEmailService(db).reset_password(
        "one-time-secret",
        "a-new-secure-password",
    )

    assert token.used_at is not None
    assert user.email_verified_at is not None
    assert user.email_verification_required is False
    assert bcryptContext.verify("a-new-secure-password", user.password)
    assert db.commits == 1
    assert len(db.executed_statements) == 3


@pytest.mark.anyio
async def test_password_reset_rejects_unknown_token():
    db = FakeAsyncSession([FakeResult(row=None)])

    with pytest.raises(ValueError, match="invalid or has expired"):
        await AccountEmailService(db).reset_password(
            "unknown-token",
            "a-new-secure-password",
        )

    assert db.commits == 0


@pytest.mark.anyio
async def test_account_activation_sets_password_and_verifies_email():
    token = UserEmailToken(
        user_id=12,
        token_hash=AccountEmailService.hash_token("activation-secret"),
        purpose=ACCOUNT_ACTIVATION,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        used_at=None,
    )
    user = User(
        id_user=12,
        name="invited-user",
        email="invited@example.com",
        password="provisional-password-hash",
        email_verified_at=None,
        email_verification_required=True,
        deleted="N",
    )
    db = FakeAsyncSession([FakeResult(row=(token, user))])

    await AccountEmailService(db).activate_account(
        "activation-secret",
        "a-new-secure-password",
    )

    assert token.used_at is not None
    assert user.email_verified_at is not None
    assert user.email_verification_required is False
    assert bcryptContext.verify("a-new-secure-password", user.password)
    assert db.commits == 1


@pytest.mark.anyio
async def test_login_blocks_new_user_until_email_is_verified():
    user = User(
        id_user=9,
        name="field-user",
        email="field@example.com",
        password=bcryptContext.hash("account-password"),
        email_verified_at=None,
        email_verification_required=True,
        deleted="N",
    )
    db = FakeAsyncSession([FakeResult(scalar=user)])

    with pytest.raises(HTTPException) as error:
        await UserService(db).auth_user(
            username="field-user",
            password="account-password",
        )

    assert error.value.status_code == 403


def test_password_reset_requires_long_password():
    with pytest.raises(ValueError):
        PasswordResetRequest(token="x" * 32, new_password="short")
