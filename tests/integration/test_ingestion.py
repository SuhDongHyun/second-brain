import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.knowledge.infra.embedding import EmbeddingError
from app.modules.knowledge.infra.models import Chunk, Document, DocumentVersion
from app.modules.knowledge.service.ingest_markdown import IngestionResult, ingest_markdown

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required for PostgreSQL ingestion tests",
)


class FakeEmbeddingProvider:
    dimensions = 1024
    is_local = True

    def __init__(self) -> None:
        self.calls = 0

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[0.0] * self.dimensions for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.0] * self.dimensions


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("embedding failed")


class WrongDimensionsProvider(FakeEmbeddingProvider):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]


class RemoteEmbeddingProvider(FakeEmbeddingProvider):
    is_local = False


@pytest.fixture
async def sessions(
    migrated_test_database: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(migrated_test_database)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE TABLE documents CASCADE"))
        yield session_factory
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE TABLE documents CASCADE"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_unchanged_and_update(
    markdown_file: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeEmbeddingProvider()
    original_content = markdown_file.read_text(encoding="utf-8")

    async with sessions() as session:
        assert await ingest_markdown(markdown_file, session, provider) == IngestionResult.CREATED
    async with sessions() as session:
        assert await ingest_markdown(markdown_file, session, provider) == IngestionResult.UNCHANGED
    assert provider.calls == 1

    async with sessions() as session:
        document = await session.scalar(select(Document))
        chunk = await session.scalar(select(Chunk))
        assert document is not None
        assert chunk is not None
        assert document.source_path == str(markdown_file.resolve())
        assert document.title == "샘플 문서"
        assert document.tags == ["sample"]
        assert len(chunk.embedding) == 1024

    markdown_file.write_text(
        markdown_file.read_text(encoding="utf-8").replace(
            "테스트 본문입니다.",
            "수정된 테스트 본문입니다.",
        ),
        encoding="utf-8",
    )
    async with sessions() as session:
        assert await ingest_markdown(markdown_file, session, provider) == IngestionResult.UPDATED

    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
        assert await session.scalar(select(func.count()).select_from(DocumentVersion)) == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DocumentVersion)
                .where(DocumentVersion.is_current.is_(True))
            )
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(Chunk)) >= 2

    markdown_file.write_text(original_content, encoding="utf-8")
    async with sessions() as session:
        assert await ingest_markdown(markdown_file, session, provider) == IngestionResult.UPDATED

    async with sessions() as session:
        versions = (
            await session.scalars(select(DocumentVersion).order_by(DocumentVersion.version))
        ).all()
        assert [version.version for version in versions] == [1, 2, 3]
        assert versions[0].content_hash == versions[2].content_hash
        assert [version.is_current for version in versions] == [False, False, True]
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_metadata_only_change_creates_new_version(
    markdown_file: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeEmbeddingProvider()
    async with sessions() as session:
        assert await ingest_markdown(markdown_file, session, provider) == IngestionResult.CREATED

    markdown_file.write_text(
        markdown_file.read_text(encoding="utf-8").replace(
            "title: 샘플 문서",
            "title: 수정된 샘플 문서",
        ),
        encoding="utf-8",
    )
    async with sessions() as session:
        assert await ingest_markdown(markdown_file, session, provider) == IngestionResult.UPDATED

    async with sessions() as session:
        document = await session.scalar(select(Document))
        versions = (
            await session.scalars(select(DocumentVersion).order_by(DocumentVersion.version))
        ).all()
        assert document is not None
        assert document.title == "수정된 샘플 문서"
        assert [version.version for version in versions] == [1, 2]
        assert [version.is_current for version in versions] == [False, True]
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_computed_content_hash_replaces_front_matter_value(
    markdown_file: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    markdown_file.write_text(
        markdown_file.read_text(encoding="utf-8").replace(
            "content_version: 1",
            "content_version: 1\ncontent_hash: sha256:stale",
        ),
        encoding="utf-8",
    )

    async with sessions() as session:
        assert (
            await ingest_markdown(markdown_file, session, FakeEmbeddingProvider())
            == IngestionResult.CREATED
        )

    async with sessions() as session:
        document = await session.scalar(select(Document))
        version = await session.scalar(select(DocumentVersion))
        assert document is not None
        assert version is not None
        assert document.metadata_["content_hash"] == version.content_hash
        assert document.metadata_["content_hash"] != "sha256:stale"


@pytest.mark.asyncio
async def test_unchanged_document_updates_moved_source_path(
    markdown_file: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeEmbeddingProvider()
    async with sessions() as session:
        assert await ingest_markdown(markdown_file, session, provider) == IngestionResult.CREATED

    moved_path = markdown_file.with_name("moved.md")
    markdown_file.rename(moved_path)
    async with sessions() as session:
        assert await ingest_markdown(moved_path, session, provider) == IngestionResult.UNCHANGED

    async with sessions() as session:
        document = await session.scalar(select(Document))
        assert document is not None
        assert document.source_path == str(moved_path.resolve())
    assert provider.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", [FailingEmbeddingProvider, WrongDimensionsProvider])
async def test_embedding_failure_preserves_current_version(
    markdown_file: Path,
    sessions: async_sessionmaker[AsyncSession],
    provider_type: type[FakeEmbeddingProvider],
) -> None:
    async with sessions() as session:
        assert (
            await ingest_markdown(markdown_file, session, FakeEmbeddingProvider())
            == IngestionResult.CREATED
        )

    markdown_file.write_text(
        markdown_file.read_text(encoding="utf-8").replace(
            "테스트 본문입니다.",
            "실패해야 하는 수정 본문입니다.",
        ),
        encoding="utf-8",
    )
    async with sessions() as session:
        with pytest.raises(EmbeddingError):
            await ingest_markdown(markdown_file, session, provider_type())

    async with sessions() as session:
        versions = (await session.scalars(select(DocumentVersion))).all()
        assert len(versions) == 1
        assert versions[0].version == 1
        assert versions[0].is_current is True
        assert await session.scalar(select(func.count()).select_from(Chunk)) == 1


@pytest.mark.asyncio
async def test_local_only_document_rejects_remote_embedding_provider(
    markdown_file: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    markdown_file.write_text(
        markdown_file.read_text(encoding="utf-8").replace(
            "llm_policy: external_allowed",
            "llm_policy: local_only",
        ),
        encoding="utf-8",
    )

    async with sessions() as session:
        with pytest.raises(EmbeddingError, match="local-only"):
            await ingest_markdown(markdown_file, session, RemoteEmbeddingProvider())
