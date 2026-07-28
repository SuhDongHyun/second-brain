from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

LEGACY_ENV_PATHS = {
    "database_url": ("database", "url"),
    "ollama_base_url": ("embedding", "base_url"),
    "embedding_model": ("embedding", "model"),
    "embedding_dimensions": ("embedding", "dimensions"),
    "ollama_timeout_seconds": ("embedding", "timeout_seconds"),
    "opendart_api_key": ("opendart", "api_key"),
    "opendart_base_url": ("opendart", "base_url"),
    "opendart_timeout_seconds": ("opendart", "timeout_seconds"),
    "opendart_raw_dir": ("opendart", "raw_dir"),
    "opendart_markdown_dir": ("opendart", "markdown_dir"),
}


class YamlSettingSource(PydanticBaseSettingsSource):
    """Load project YAML values as a Pydantic settings source.
    Values are read lazily when Pydantic resolves the configured sources."""

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        yaml_file: str = "config.yaml",
    ) -> None:
        """Initialize the source with its settings type and YAML filename.
        The path is resolved relative to the project when values are requested."""

        super().__init__(settings_cls)
        self.yaml_file = yaml_file

    def get_field_value(
        self,
        field: FieldInfo,
        field_name: str,
    ) -> tuple[object, str, bool]:
        """Return Pydantic's sentinel result for unsupported field lookup.
        This source supplies its configuration as one complete mapping instead."""

        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        """Return all YAML values for Pydantic's source merge.
        Missing files and empty documents are represented by an empty mapping."""

        return self._read_yaml()

    def _read_yaml(self) -> dict[str, Any]:
        """Read and deserialize the configured project YAML file.
        The helper keeps optional configuration files from failing startup."""

        file_path = Path(__file__).resolve().parent.parent / self.yaml_file
        if not file_path.exists():
            return {}

        with file_path.open("r", encoding="utf-8") as file:
            config_yaml = yaml.safe_load(file) or {}

        return config_yaml


class LegacyFlatSettingsSource(PydanticBaseSettingsSource):
    """Map the original flat environment names into nested settings.
    The wrapper preserves deployed configuration while newer names take priority."""

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        env_vars: Mapping[str, str | None],
    ) -> None:
        """Initialize the compatibility source from a parsed environment mapping.
        Pydantic's environment and dotenv sources provide normalized lowercase keys."""

        super().__init__(settings_cls)
        self.env_vars = env_vars

    def get_field_value(
        self,
        field: FieldInfo,
        field_name: str,
    ) -> tuple[object, str, bool]:
        """Return Pydantic's sentinel result for unsupported field lookup.
        Compatibility values are emitted as one nested mapping instead."""

        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        """Return legacy variables grouped under their current settings models.
        Missing variables are omitted so lower-priority sources can provide defaults."""

        values: dict[str, Any] = {}
        for env_name, (section, field_name) in LEGACY_ENV_PATHS.items():
            value = self.env_vars.get(env_name)
            if value is not None:
                values.setdefault(section, {})[field_name] = value
        return values


class DatabaseSettings(BaseModel):
    """Describe database URLs for runtime and isolated test environments.
    Pydantic validates these values before engines or migrations consume them."""

    url: str
    test_url: str
    migration_test_url: str


class EmbeddingSettings(BaseModel):
    """Describe the Ollama endpoint, model, dimensions, and timeout.
    Validation keeps generated vectors compatible with the database schema."""

    base_url: AnyHttpUrl
    model: str
    dimensions: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)

    @field_validator("dimensions")
    @classmethod
    def require_schema_dimensions(cls, value: int) -> int:
        """Require the embedding size fixed by the pgvector column.
        A mismatched setting fails before any embedding request is attempted."""
        if value != 1024:
            raise ValueError("EMBEDDING__DIMENSIONS must match the database vector(1024) schema")
        return value


class OpenDartSettings(BaseModel):
    """Describe OpenDART access and financial artifact locations.
    The model validates endpoint and timeout values used by the adapter."""

    api_key: str = ""
    base_url: AnyHttpUrl
    timeout_seconds: float = Field(gt=0)
    raw_dir: Path
    markdown_dir: Path


class AdkSettings(BaseModel):
    """Describe Google ADK model access and bounded answer context.
    The API key remains optional until the answer endpoint is invoked."""

    api_key: str = ""
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)
    app_name: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    max_context_tokens: int = Field(gt=0)
    max_results: int = Field(ge=1, le=8)


class Settings(BaseSettings):
    """Combine runtime, environment, dotenv, YAML, and secret settings.
    Nested models expose validated configuration to application composition."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        env_nested_delimiter="__",
    )

    database: DatabaseSettings
    embedding: EmbeddingSettings
    opendart: OpenDartSettings
    adk: AdkSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Define the precedence of every application settings source.
        YAML values sit below explicit, environment, and dotenv overrides."""

        return (
            init_settings,
            env_settings,
            LegacyFlatSettingsSource(settings_cls, env_settings.env_vars),
            dotenv_settings,
            LegacyFlatSettingsSource(settings_cls, dotenv_settings.env_vars),
            YamlSettingSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    """Create and cache the validated application settings.
    Repeated dependency lookups share one immutable configuration snapshot."""

    return Settings()
