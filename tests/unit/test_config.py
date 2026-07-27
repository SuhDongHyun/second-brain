import pytest
from pydantic import ValidationError

from app.config import Settings


def test_embedding_dimensions_match_database_schema() -> None:
    assert Settings(embedding_dimensions=1024).embedding_dimensions == 1024

    with pytest.raises(ValidationError, match=r"vector\(1024\)"):
        Settings(embedding_dimensions=768)


def test_opendart_settings_have_portable_defaults() -> None:
    settings = Settings(_env_file=None, opendart_api_key="x" * 40)

    assert settings.opendart_api_key == "x" * 40
    assert str(settings.opendart_base_url) == "https://opendart.fss.or.kr/api"
    assert settings.opendart_timeout_seconds == 30
    assert str(settings.opendart_raw_dir) == "raw/opendart"
    assert str(settings.opendart_markdown_dir) == "knowledge/generated/opendart"
