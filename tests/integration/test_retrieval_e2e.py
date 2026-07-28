import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.knowledge.domain.retrieval import SearchFilters
from app.modules.knowledge.service.ingest_markdown import IngestionResult, ingest_markdown
from app.modules.knowledge.service.search_knowledge import hybrid_search

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required for PostgreSQL retrieval tests",
)


class SemanticFakeEmbeddingProvider:
    dimensions = 1024
    is_local = True

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        normalized = text.lower()
        vector = [0.0] * self.dimensions
        if "oracle" in normalized or "adk" in normalized:
            vector[0] = 1.0
        if "trading-api" in normalized or "투자 에이전트" in normalized:
            vector[1] = 1.0
        if not any(vector):
            vector[2] = 1.0
        return vector


@pytest.fixture
async def retrieval_session(migrated_test_database: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_test_database)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE documents CASCADE"))

    async with session_factory() as session:
        yield session

    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE documents CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_blueprint_questions_find_expected_sources(
    retrieval_session: AsyncSession,
) -> None:
    provider = SemanticFakeEmbeddingProvider()
    samples = [
        Path("knowledge/samples/11-oracle-adk-troubleshooting.md"),
        Path("knowledge/samples/12-trading-api-role.md"),
    ]
    for sample in samples:
        assert await ingest_markdown(sample, retrieval_session, provider) == IngestionResult.CREATED

    oracle_results = await hybrid_search(
        "Oracle Cloud에서 ADK 접속 문제를 어떻게 해결했지?",
        retrieval_session,
        provider,
        SearchFilters(limit=3),
    )
    trading_results = await hybrid_search(
        "trading-api는 어떤 역할을 하는 프로젝트야?",
        retrieval_session,
        provider,
        SearchFilters(limit=3),
    )

    assert oracle_results[0].metadata["source_key"] == "sample-oracle-adk-troubleshooting"
    assert trading_results[0].metadata["source_key"] == "sample-trading-api-role"
