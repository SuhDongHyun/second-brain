from functools import lru_cache

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://second_brain:second_brain@localhost:5432/second_brain"
    ollama_base_url: AnyHttpUrl = "http://localhost:11434"
    embedding_model: str = "bge-m3"
    embedding_dimensions: int = Field(default=1024, gt=0)
    ollama_timeout_seconds: float = Field(default=60, gt=0)

    @field_validator("embedding_dimensions")
    @classmethod
    def require_schema_dimensions(cls, value: int) -> int:
        if value != 1024:
            raise ValueError("EMBEDDING_DIMENSIONS must match the database vector(1024) schema")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
