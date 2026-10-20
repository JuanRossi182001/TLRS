"""Shared pytest configuration and safe disposable test database fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


_INTEGRATION_DATABASE_WAS_EXPLICITLY_CONFIGURED = "TEST_DATABASE_URL" in os.environ
_DEFAULT_TEST_DATABASE_URL = (
    "postgresql://tlrs_test:tlrs_test@127.0.0.1:55432/tlrs_test"
)


def _validated_test_database_url() -> URL:
    raw_url = os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DATABASE_URL)
    parsed_url = make_url(raw_url)
    if (
        parsed_url.host not in {"localhost", "127.0.0.1", "::1"}
        or parsed_url.port != 55432
        or parsed_url.database != "tlrs_test"
        or parsed_url.username != "tlrs_test"
    ):
        raise RuntimeError(
            "TEST_DATABASE_URL must point to the local disposable tlrs_test "
            "database on port 55432 using the tlrs_test user. Refusing to run tests against "
            "a non-test database."
        )
    return parsed_url


_TEST_DATABASE_URL = _validated_test_database_url()
TEST_ASYNC_DATABASE_URL = _TEST_DATABASE_URL.set(
    drivername="postgresql+asyncpg"
).render_as_string(hide_password=False)
TEST_SYNC_DATABASE_URL = _TEST_DATABASE_URL.set(
    drivername="postgresql+psycopg2"
).render_as_string(hide_password=False)

# Settings load environment variables before .env values. Force the app's
# module-level engine and Alembic to use the local test database during pytest.
os.environ["DB_CONNECTION_URL"] = TEST_SYNC_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_SYNC_DATABASE_URL


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep integration tests opt-in unless TEST_DATABASE_URL is explicit."""
    if _INTEGRATION_DATABASE_WAS_EXPLICITLY_CONFIGURED:
        return

    skip_integration = pytest.mark.skip(
        reason=(
            "Set TEST_DATABASE_URL and start docker-compose.test.yml to run "
            "database integration tests."
        )
    )
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_integration)


@pytest.fixture(scope="session")
def migrated_test_database() -> Iterator[None]:
    """Apply Alembic migrations to the isolated test database.

    The existing migration chain assumes role id 1 exists before revision
    ``a7f43b6d9211``. Seed that prerequisite in the disposable database only.
    """
    from alembic import command
    from alembic.config import Config

    repository_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(repository_root / "alembic.ini"))
    command.upgrade(alembic_config, "5b4b3db4ef01")

    sync_engine = create_engine(TEST_SYNC_DATABASE_URL)
    try:
        with sync_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO roles (id_role, name, deleted) "
                    "VALUES (1, 'pytest-default-role', 'N')"
                )
            )
            connection.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('roles', 'id_role'), "
                    "(SELECT max(id_role) FROM roles))"
                )
            )
    finally:
        sync_engine.dispose()

    command.upgrade(alembic_config, "head")
    yield


@pytest.fixture
async def test_session_factory(
    migrated_test_database: None,
    anyio_backend: str,
) -> AsyncIterator[async_sessionmaker]:
    """Provide async SQLAlchemy sessions against the migrated test database."""
    engine = create_async_engine(TEST_ASYNC_DATABASE_URL, pool_pre_ping=True)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
