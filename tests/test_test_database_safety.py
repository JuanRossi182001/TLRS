import pytest

from tests.conftest import _validated_test_database_url


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://tlrs_test:tlrs_test@db.example.com:55432/tlrs_test",
        "postgresql://tlrs_test:tlrs_test@127.0.0.1:5432/tlrs_test",
        "postgresql://tlrs_test:tlrs_test@127.0.0.1:55432/production",
        "postgresql://other_user:secret@127.0.0.1:55432/tlrs_test",
    ],
    ids=["remote-host", "wrong-port", "wrong-database", "wrong-user"],
)
def test_database_url_guard_rejects_non_disposable_database(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", database_url)

    with pytest.raises(RuntimeError, match="Refusing to run tests"):
        _validated_test_database_url()


def test_database_url_guard_accepts_only_local_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = "postgresql://tlrs_test:tlrs_test@127.0.0.1:55432/tlrs_test"
    monkeypatch.setenv("TEST_DATABASE_URL", database_url)

    parsed_url = _validated_test_database_url()

    assert parsed_url.host == "127.0.0.1"
    assert parsed_url.port == 55432
    assert parsed_url.database == "tlrs_test"
