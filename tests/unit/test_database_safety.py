import pytest
from conftest import _database_identity, _validate_test_database_urls


def test_database_identity_normalizes_common_postgresql_aliases() -> None:
    without_port = "postgresql+asyncpg://user:password@localhost/example"
    explicit_port = "postgresql+asyncpg://other:secret@127.0.0.1:5432/example"
    trailing_dot = "postgresql+asyncpg://user:password@LOCALHOST.:5432/example"

    assert _database_identity(without_port) == _database_identity(explicit_port)
    assert _database_identity(without_port) == _database_identity(trailing_dot)


def test_database_safety_rejects_effective_application_database() -> None:
    database_url = "postgresql+asyncpg://user:password@localhost/second_brain_test"

    with pytest.raises(pytest.UsageError, match="DATABASE_URL"):
        _validate_test_database_urls(
            database_url,
            {"TEST_DATABASE_URL": database_url},
        )


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://user:password@localhost/second_brain",
        "postgresql+asyncpg://user:password@database/second_brain_test",
    ],
)
def test_database_safety_requires_explicit_local_test_database(
    database_url: str,
) -> None:
    with pytest.raises(pytest.UsageError, match="loopback database"):
        _validate_test_database_urls(
            "postgresql+asyncpg://user:password@localhost/second_brain",
            {"TEST_DATABASE_URL": database_url},
        )
