import pytest
from pydantic import ValidationError

from app.config import Settings


def test_embedding_dimensions_match_database_schema() -> None:
    assert Settings(embedding_dimensions=1024).embedding_dimensions == 1024

    with pytest.raises(ValidationError, match=r"vector\(1024\)"):
        Settings(embedding_dimensions=768)
