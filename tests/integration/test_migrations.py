import os
import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    "MIGRATION_TEST_DATABASE_URL" not in os.environ,
    reason="MIGRATION_TEST_DATABASE_URL is required for destructive migration tests",
)


def _migration_environment() -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": os.environ["MIGRATION_TEST_DATABASE_URL"],
    }


def _run_alembic(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "alembic", *arguments],
        check=check,
        capture_output=not check,
        env=_migration_environment(),
        text=True,
    )


def test_migrations_upgrade_downgrade_upgrade() -> None:
    _run_alembic("downgrade", "base")
    try:
        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "base")
        _run_alembic("upgrade", "head")
    finally:
        _run_alembic("downgrade", "base")


@pytest.mark.asyncio
async def test_downgrade_rejects_reverted_content_history() -> None:
    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", "head")
    engine = create_async_engine(os.environ["MIGRATION_TEST_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO documents (
                        id, source_key, source_path, title, source_type, document_type,
                        domain, access_scope, llm_policy, created_at, updated_at,
                        observed_at, tags, metadata, is_deleted
                    ) VALUES (
                        '00000000-0000-0000-0000-000000000001',
                        'migration-revert-test', '/tmp/test.md', 'Migration test',
                        'test', 'test', 'test', 'private', 'external_allowed',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                        '[]'::jsonb, '{}'::jsonb, false
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO document_versions (
                        id, document_id, version, content_path, normalized_content,
                        content_hash, is_current
                    ) VALUES
                        (
                            '00000000-0000-0000-0000-000000000011',
                            '00000000-0000-0000-0000-000000000001',
                            1, '/tmp/test.md', 'original', 'sha256:duplicate', false
                        ),
                        (
                            '00000000-0000-0000-0000-000000000012',
                            '00000000-0000-0000-0000-000000000001',
                            2, '/tmp/test.md', 'reverted', 'sha256:duplicate', true
                        )
                    """
                )
            )

        result = _run_alembic("downgrade", "0001", check=False)
        assert result.returncode != 0
        assert "Cannot downgrade 0002 while reverted document content exists" in result.stderr
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM documents WHERE source_key = 'migration-revert-test'")
            )
        await engine.dispose()
        _run_alembic("downgrade", "base")
