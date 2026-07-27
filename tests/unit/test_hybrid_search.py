import uuid
from unittest.mock import AsyncMock

import pytest

import app.retrieval as retrieval
from app.retrieval import RetrievalCandidate, SearchFilters, hybrid_search


class FakeEmbeddingProvider:
    dimensions = 1024
    is_local = True

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("document embedding must not be used for search")

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.0] * self.dimensions


def candidate(label: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"chunk:{label}"),
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, f"document:{label}"),
        document_version_id=uuid.uuid5(uuid.NAMESPACE_URL, f"version:{label}"),
        title=label,
        source_path=f"knowledge/{label}.md",
        heading_path=("Overview",),
        chunk_text=f"Body {label}",
        metadata={},
    )


@pytest.mark.asyncio
async def test_hybrid_search_embeds_once_and_fuses_both_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = candidate("shared")
    keyword_only = candidate("keyword")
    vector_only = candidate("vector")
    keyword_search = AsyncMock(return_value=[shared, keyword_only])
    vector_search = AsyncMock(return_value=[vector_only, shared])
    monkeypatch.setattr(retrieval, "search_keywords", keyword_search)
    monkeypatch.setattr(retrieval, "search_vectors", vector_search)
    provider = FakeEmbeddingProvider()
    filters = SearchFilters(limit=2)
    session = object()

    results = await hybrid_search(
        "  Oracle ADK  ",
        session,  # type: ignore[arg-type]
        provider,
        filters,
    )

    assert provider.queries == ["Oracle ADK"]
    keyword_search.assert_awaited_once_with(
        session,
        "Oracle ADK",
        filters,
        candidate_limit=20,
    )
    vector_search.assert_awaited_once_with(
        session,
        [0.0] * 1024,
        filters,
        candidate_limit=20,
    )
    assert [result.chunk_id for result in results] == [shared.chunk_id, vector_only.chunk_id]


@pytest.mark.asyncio
async def test_hybrid_search_returns_results_from_one_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vector_only = candidate("vector")
    monkeypatch.setattr(retrieval, "search_keywords", AsyncMock(return_value=[]))
    monkeypatch.setattr(retrieval, "search_vectors", AsyncMock(return_value=[vector_only]))

    results = await hybrid_search(
        "query",
        object(),  # type: ignore[arg-type]
        FakeEmbeddingProvider(),
        SearchFilters(limit=5),
    )

    assert len(results) == 1
    assert results[0].matched_by == ("vector",)


@pytest.mark.asyncio
async def test_hybrid_search_rejects_blank_query_before_embedding() -> None:
    provider = FakeEmbeddingProvider()

    with pytest.raises(ValueError, match="query"):
        await hybrid_search(
            " ",
            object(),  # type: ignore[arg-type]
            provider,
            SearchFilters(),
        )

    assert provider.queries == []
