import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.knowledge.domain.retrieval import SearchFilters
from app.modules.knowledge.infra.models import Chunk, Document, DocumentVersion
from app.modules.knowledge.infra.retrieval import search_keywords, search_vectors

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required for PostgreSQL retrieval tests",
)


@pytest.fixture
async def retrieval_session(migrated_test_database: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_test_database)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE documents CASCADE"))

    async with session_factory() as session:
        await _seed_retrieval_documents(session)
        await session.commit()
        yield session

    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE documents CASCADE"))
    await engine.dispose()


async def _seed_retrieval_documents(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    await _add_document(
        session,
        source_key="oracle-adk",
        title="Oracle Cloud ADK 접속 문제 해결",
        body="Oracle Cloud 방화벽과 ADK endpoint 설정을 확인하여 접속 문제를 해결했다.",
        vector=_vector(0),
        project="second-brain",
        domain="development",
        source_type="personal_note",
        document_type="troubleshooting",
        tags=["oracle-cloud", "google-adk"],
        updated_at=now,
    )
    await _add_document(
        session,
        source_key="trading-api",
        title="trading-api 프로젝트",
        body="trading-api는 주문과 시세 조회를 제공하는 FastAPI 서비스다.",
        vector=_vector(1),
        project="investment-agents",
        domain="finance",
        source_type="project_note",
        document_type="overview",
        tags=["fastapi", "trading"],
        updated_at=now - timedelta(days=30),
    )
    await _add_document(
        session,
        source_key="deleted-adk",
        title="삭제된 ADK 문서",
        body="ADK endpoint에 대한 오래된 해결 방법",
        vector=_vector(2),
        project="second-brain",
        domain="development",
        source_type="personal_note",
        document_type="troubleshooting",
        tags=["google-adk"],
        updated_at=now,
        is_deleted=True,
    )
    await _add_document(
        session,
        source_key="versioned-adk",
        title="버전이 있는 문서",
        body="현재 버전에는 새로운 내용만 있다.",
        vector=_vector(3),
        project="second-brain",
        domain="development",
        source_type="personal_note",
        document_type="note",
        tags=["versioned"],
        updated_at=now,
        old_body="ADK 과거 버전은 검색되면 안 된다.",
    )


async def _add_document(
    session: AsyncSession,
    *,
    source_key: str,
    title: str,
    body: str,
    vector: list[float],
    project: str,
    domain: str,
    source_type: str,
    document_type: str,
    tags: list[str],
    updated_at: datetime,
    is_deleted: bool = False,
    old_body: str | None = None,
) -> None:
    document = Document(
        source_key=source_key,
        source_path=f"knowledge/{source_key}.md",
        title=title,
        source_type=source_type,
        document_type=document_type,
        domain=domain,
        project=project,
        language="ko",
        access_scope="private",
        llm_policy="external_allowed",
        created_at=updated_at,
        updated_at=updated_at,
        observed_at=updated_at,
        tags=tags,
        metadata_={"source_key": source_key},
        is_deleted=is_deleted,
    )
    session.add(document)
    if old_body is not None:
        old_version = _version(document, old_body, vector, version=1, is_current=False)
        session.add(old_version)
    session.add(
        _version(
            document,
            body,
            vector,
            version=2 if old_body is not None else 1,
            is_current=True,
        )
    )


def _version(
    document: Document,
    body: str,
    vector: list[float],
    *,
    version: int,
    is_current: bool,
) -> DocumentVersion:
    document_version = DocumentVersion(
        document=document,
        version=version,
        content_path=document.source_path,
        normalized_content=body,
        content_hash=f"sha256:{version:064x}",
        is_current=is_current,
    )
    document_version.chunks.append(
        Chunk(
            chunk_index=0,
            heading_path=["개요"],
            chunk_type="section",
            chunk_text=body,
            token_count=len(body.split()),
            content_hash=f"sha256:{uuid.uuid5(uuid.NAMESPACE_URL, body).hex:0>64}",
            metadata_={"version": version},
            embedding=vector,
        )
    )
    return document_version


def _vector(index: int) -> list[float]:
    vector = [0.0] * 1024
    vector[index] = 1.0
    return vector


@pytest.mark.asyncio
async def test_keyword_search_returns_current_non_deleted_chunks(
    retrieval_session: AsyncSession,
) -> None:
    results = await search_keywords(
        retrieval_session,
        "ADK 접속 문제",
        SearchFilters(),
        candidate_limit=10,
    )

    assert [result.title for result in results] == ["Oracle Cloud ADK 접속 문제 해결"]
    assert results[0].heading_path == ("개요",)
    assert results[0].metadata["updated_at"]
    assert "valid_from" in results[0].metadata
    assert "valid_to" in results[0].metadata


@pytest.mark.asyncio
async def test_vector_search_orders_by_cosine_distance(
    retrieval_session: AsyncSession,
) -> None:
    query = _vector(1)
    query[0] = 0.2

    results = await search_vectors(
        retrieval_session,
        query,
        SearchFilters(),
        candidate_limit=2,
    )

    assert [result.title for result in results] == [
        "trading-api 프로젝트",
        "Oracle Cloud ADK 접속 문제 해결",
    ]


@pytest.mark.asyncio
async def test_search_applies_combined_metadata_filters(
    retrieval_session: AsyncSession,
) -> None:
    filters = SearchFilters(
        project="second-brain",
        domain="development",
        source_type="personal_note",
        document_type="troubleshooting",
        tags=["oracle-cloud", "google-adk"],
        updated_from=datetime.now(UTC) - timedelta(days=1),
    )

    keyword_results = await search_keywords(
        retrieval_session,
        "Oracle",
        filters,
        candidate_limit=10,
    )
    vector_results = await search_vectors(
        retrieval_session,
        _vector(0),
        filters,
        candidate_limit=10,
    )

    assert [result.title for result in keyword_results] == ["Oracle Cloud ADK 접속 문제 해결"]
    assert [result.title for result in vector_results] == ["Oracle Cloud ADK 접속 문제 해결"]


@pytest.mark.asyncio
async def test_search_rejects_invalid_inputs_before_database_call(
    retrieval_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="query"):
        await search_keywords(retrieval_session, " ", SearchFilters(), candidate_limit=10)
    with pytest.raises(ValueError, match="1024"):
        await search_vectors(retrieval_session, [1.0, 0.0], SearchFilters(), candidate_limit=10)
    with pytest.raises(ValueError, match="candidate_limit"):
        await search_keywords(retrieval_session, "ADK", SearchFilters(), candidate_limit=0)
