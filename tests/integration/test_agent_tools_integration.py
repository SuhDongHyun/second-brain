import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.agent.domain.answer import ToolTrace
from app.modules.agent.service.tools import create_retriever_tools
from app.modules.knowledge.domain.retrieval import SearchFilters
from app.modules.knowledge.infra.models import Chunk, Document, DocumentVersion

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required for agent Tool integration tests",
)


class FakeEmbeddingProvider:
    """Return a fixed schema-compatible query vector without external I/O."""

    dimensions = 1024
    is_local = True

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Reject document embedding because integration fixtures are pre-seeded."""
        raise AssertionError(f"unexpected document embedding: {texts}")

    async def embed_query(self, text: str) -> list[float]:
        """Return the vector shared by the seeded relevant chunks."""
        assert text.strip()
        return _vector()


@pytest.fixture
async def agent_tool_session(migrated_test_database: str) -> AsyncIterator[AsyncSession]:
    """Provide an empty transaction-capable PostgreSQL session per Tool test."""
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
async def test_agent_tools_use_real_hybrid_retrieval_and_source_chain(
    agent_tool_session: AsyncSession,
) -> None:
    await _add_document(
        agent_tool_session,
        source_key="oracle-adk",
        title="Oracle ADK 접속 해결",
        body="Oracle 방화벽과 ADK endpoint 설정으로 접속 문제를 해결했다.",
        domain="development",
        source_type="personal_note",
        llm_policy="external_allowed",
    )
    await _add_document(
        agent_tool_session,
        source_key="opendart-samsung",
        title="삼성전자 사업보고서",
        body="연결재무제표 (CFS) 영업이익 1,000원 접수번호 20260317001234",
        domain="finance",
        source_type="opendart",
        llm_policy="external_allowed",
        receipt_number="20260317001234",
    )
    await agent_tool_session.commit()
    trace = ToolTrace()
    tools = create_retriever_tools(
        session=agent_tool_session,
        embedding_provider=FakeEmbeddingProvider(),
        request_filters=SearchFilters(limit=6),
        trace=trace,
        max_context_tokens=6000,
        max_results=6,
    )

    general = await tools.search_knowledge("Oracle ADK 접속")
    financial = await tools.query_financial_facts("삼성전자", metric="영업이익")

    assert general["status"] == "ok"
    assert any(item["title"] == "Oracle ADK 접속 해결" for item in general["results"])
    assert financial["status"] == "ok"
    assert financial["results"][0]["title"] == "삼성전자 사업보고서"
    assert financial["results"][0]["source_reference"] == "20260317001234"
    assert trace.summary.route == "financial_hybrid"


@pytest.mark.asyncio
async def test_agent_tools_never_return_local_only_text(
    agent_tool_session: AsyncSession,
) -> None:
    secret = "외부 모델로 보내면 안 되는 민감한 개인 기록"
    await _add_document(
        agent_tool_session,
        source_key="private-note",
        title="민감 문서",
        body=secret,
        domain="personal",
        source_type="personal_note",
        llm_policy="local_only",
    )
    await agent_tool_session.commit()
    trace = ToolTrace()
    tools = create_retriever_tools(
        session=agent_tool_session,
        embedding_provider=FakeEmbeddingProvider(),
        request_filters=SearchFilters(limit=6),
        trace=trace,
        max_context_tokens=6000,
        max_results=6,
    )

    payload = await tools.search_knowledge("민감 개인 기록")

    assert payload == {"status": "blocked_by_policy"}
    assert secret not in str(payload)
    assert trace.blocked_by_policy is True


async def _add_document(
    session: AsyncSession,
    *,
    source_key: str,
    title: str,
    body: str,
    domain: str,
    source_type: str,
    llm_policy: str,
    receipt_number: str | None = None,
) -> None:
    """Insert one current document and embedded chunk for retrieval tests."""
    now = datetime.now(UTC)
    metadata = {"source_key": source_key}
    if receipt_number is not None:
        metadata["receipt_number"] = receipt_number
    document = Document(
        source_key=source_key,
        source_path=f"knowledge/{source_key}.md",
        title=title,
        source_type=source_type,
        document_type="financial_report" if source_type == "opendart" else "note",
        domain=domain,
        project="second-brain",
        language="ko",
        access_scope="private",
        llm_policy=llm_policy,
        created_at=now,
        updated_at=now,
        observed_at=now,
        tags=[],
        metadata_=metadata,
        is_deleted=False,
    )
    version = DocumentVersion(
        document=document,
        version=1,
        content_path=document.source_path,
        normalized_content=body,
        content_hash=f"sha256:{uuid.uuid5(uuid.NAMESPACE_URL, source_key).hex:0>64}",
        is_current=True,
    )
    version.chunks.append(
        Chunk(
            chunk_index=0,
            heading_path=["연결재무제표 (CFS)"] if source_type == "opendart" else ["개요"],
            chunk_type="section",
            chunk_text=body,
            token_count=len(body.split()),
            content_hash=f"sha256:{uuid.uuid5(uuid.NAMESPACE_URL, body).hex:0>64}",
            metadata_={},
            embedding=_vector(),
        )
    )
    session.add(document)


def _vector() -> list[float]:
    """Return a deterministic non-zero 1024-dimensional vector."""
    vector = [0.0] * 1024
    vector[0] = 1.0
    return vector
