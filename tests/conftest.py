import os
import subprocess
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import make_url

from app.config import Settings


def _database_identity(database_url: str) -> tuple[str | None, int, str | None]:
    url = make_url(database_url)
    host = url.host.lower().rstrip(".") if url.host else None
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "loopback"
    return host, url.port or 5432, url.database


def _run_alembic(database_url: str, *arguments: str) -> None:
    environment = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(
        ["uv", "run", "alembic", *arguments],
        check=True,
        env=environment,
    )


def _validate_test_database_urls(
    effective_database_url: str,
    test_database_urls: dict[str, str | None],
) -> None:
    identities = {_database_identity(effective_database_url): "DATABASE_URL"}
    for name, database_url in test_database_urls.items():
        if database_url is None:
            continue
        host, _, database = _database_identity(database_url)
        if host != "loopback" or database is None or not database.endswith("_test"):
            raise pytest.UsageError(
                f"{name} must reference a loopback database whose name ends with '_test'"
            )
        identity = _database_identity(database_url)
        if previous_name := identities.get(identity):
            raise pytest.UsageError(
                f"{name} and {previous_name} must reference different databases"
            )
        identities[identity] = name


@pytest.fixture(scope="session", autouse=True)
def validate_test_database_urls() -> Iterator[None]:
    test_database_urls = {
        name: os.getenv(name) for name in ("TEST_DATABASE_URL", "MIGRATION_TEST_DATABASE_URL")
    }
    _validate_test_database_urls(Settings().database_url, test_database_urls)
    yield


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database(
    validate_test_database_urls: None,
) -> Iterator[str | None]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        yield None
        return

    _run_alembic(database_url, "downgrade", "base")
    _run_alembic(database_url, "upgrade", "head")
    try:
        yield database_url
    finally:
        _run_alembic(database_url, "downgrade", "base")


@pytest.fixture
def metadata() -> dict[str, Any]:
    timestamp = datetime.fromisoformat("2026-07-26T12:00:00+09:00")
    return {
        "id": "sample-document",
        "title": "샘플 문서",
        "source_type": "personal_note",
        "document_type": "note",
        "domain": "development",
        "project": "second-brain",
        "language": "ko",
        "created_at": timestamp,
        "updated_at": timestamp,
        "observed_at": timestamp,
        "valid_from": None,
        "valid_to": None,
        "tags": ["sample"],
        "access_scope": "private",
        "llm_policy": "external_allowed",
        "content_version": 1,
    }


@pytest.fixture
def markdown_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.md"
    path.write_text(
        """---
id: sample-document
title: 샘플 문서
source_type: personal_note
document_type: note
domain: development
project: second-brain
language: ko
created_at: "2026-07-26T12:00:00+09:00"
updated_at: "2026-07-26T12:00:00+09:00"
observed_at: "2026-07-26T12:00:00+09:00"
valid_from: null
valid_to: null
tags: [sample]
access_scope: private
llm_policy: external_allowed
content_version: 1
---
# 개요

테스트 본문입니다.
""",
        encoding="utf-8",
    )
    return path
