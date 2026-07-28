from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.config import Settings, get_settings


def test_embedding_dimensions_match_database_schema() -> None:
    assert Settings(_env_file=None).embedding.dimensions == 1024

    with pytest.raises(ValidationError, match=r"vector\(1024\)"):
        Settings(_env_file=None, embedding={"dimensions": 768})


def test_opendart_settings_have_portable_defaults() -> None:
    settings = Settings(_env_file=None, opendart={"api_key": "x" * 40})

    assert settings.opendart.api_key == "x" * 40
    assert str(settings.opendart.base_url) == "https://opendart.fss.or.kr/api"
    assert settings.opendart.timeout_seconds == 30
    assert str(settings.opendart.raw_dir) == "raw/opendart"
    assert str(settings.opendart.markdown_dir) == "knowledge/generated/opendart"


def test_non_secret_defaults_are_loaded_from_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None)

    assert settings.database.url.endswith("/second_brain")
    assert str(settings.embedding.base_url) == "http://localhost:11434/"
    assert settings.embedding.model == "bge-m3"
    assert settings.opendart.api_key == ""

    config = yaml.safe_load(Path("config.yaml").read_text())
    assert "api_key" not in config["opendart"]


def test_database_test_urls_are_loaded_from_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "DATABASE__URL",
        "DATABASE__TEST_URL",
        "DATABASE__MIGRATION_TEST_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.database.test_url.endswith("/second_brain_test")
    assert settings.database.migration_test_url.endswith("/second_brain_migration_test")


def test_nested_environment_variables_override_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE__URL",
        "postgresql+asyncpg://override:override@localhost:5432/override",
    )
    monkeypatch.setenv("EMBEDDING__BASE_URL", "http://127.0.0.1:22434")
    monkeypatch.setenv("EMBEDDING__MODEL", "override-model")
    monkeypatch.setenv("OPENDART__API_KEY", "secret-from-env")

    settings = Settings(_env_file=None)

    assert settings.database.url.endswith("/override")
    assert str(settings.embedding.base_url) == "http://127.0.0.1:22434/"
    assert settings.embedding.model == "override-model"
    assert settings.opendart.api_key == "secret-from-env"


def test_legacy_flat_environment_variables_override_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://legacy:legacy@localhost:5432/legacy",
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:32434")
    monkeypatch.setenv("EMBEDDING_MODEL", "legacy-model")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("OPENDART_API_KEY", "legacy-secret")
    monkeypatch.setenv("OPENDART_BASE_URL", "https://legacy.example/api")
    monkeypatch.setenv("OPENDART_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("OPENDART_RAW_DIR", "legacy/raw")
    monkeypatch.setenv("OPENDART_MARKDOWN_DIR", "legacy/markdown")

    settings = Settings(_env_file=None)

    assert settings.database.url.endswith("/legacy")
    assert str(settings.embedding.base_url) == "http://127.0.0.1:32434/"
    assert settings.embedding.model == "legacy-model"
    assert settings.embedding.dimensions == 1024
    assert settings.embedding.timeout_seconds == 45
    assert settings.opendart.api_key == "legacy-secret"
    assert str(settings.opendart.base_url) == "https://legacy.example/api"
    assert settings.opendart.timeout_seconds == 15
    assert settings.opendart.raw_dir == Path("legacy/raw")
    assert settings.opendart.markdown_dir == Path("legacy/markdown")


def test_nested_environment_variables_take_priority_over_legacy_flat_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://legacy:legacy@localhost:5432/legacy",
    )
    monkeypatch.setenv(
        "DATABASE__URL",
        "postgresql+asyncpg://nested:nested@localhost:5432/nested",
    )

    settings = Settings(_env_file=None)

    assert settings.database.url.endswith("/nested")


def test_explicit_input_has_priority_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE__URL",
        "postgresql+asyncpg://environment:environment@localhost:5432/environment",
    )

    settings = Settings(
        _env_file=None,
        database={"url": "postgresql+asyncpg://explicit:explicit@localhost:5432/explicit"},
    )

    assert settings.database.url.endswith("/explicit")


def test_environment_has_priority_over_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EMBEDDING__MODEL=dotenv-model\nOPENDART__API_KEY=dotenv-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EMBEDDING__MODEL", "environment-model")
    monkeypatch.delenv("OPENDART__API_KEY", raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.embedding.model == "environment-model"
    assert settings.opendart.api_key == "dotenv-secret"


def test_legacy_flat_dotenv_variables_override_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://legacy:legacy@localhost:5432/legacy-dotenv\n"
        "OPENDART_API_KEY=legacy-dotenv-secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE__URL", raising=False)
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    monkeypatch.delenv("OPENDART__API_KEY", raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.database.url.endswith("/legacy-dotenv")
    assert settings.opendart.api_key == "legacy-dotenv-secret"


def test_get_settings_populates_every_runtime_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENDART__API_KEY", "test-secret")
    get_settings.cache_clear()

    try:
        settings = get_settings()

        assert settings.database.url
        assert settings.database.test_url
        assert settings.database.migration_test_url
        assert settings.embedding.base_url
        assert settings.embedding.model
        assert settings.embedding.dimensions == 1024
        assert settings.embedding.timeout_seconds > 0
        assert settings.opendart.api_key == "test-secret"
        assert settings.opendart.base_url
        assert settings.opendart.timeout_seconds > 0
        assert settings.opendart.raw_dir
        assert settings.opendart.markdown_dir
    finally:
        get_settings.cache_clear()
