import uuid

import httpx
import pytest

import app.api.query as query_api
from app.api.query import get_embedding_provider
from app.db import get_session
from app.embeddings import EmbeddingError
from app.main import create_app
from app.retrieval import SearchResult


def result() -> SearchResult:
    return SearchResult(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, "chunk"),
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, "document"),
        document_version_id=uuid.uuid5(uuid.NAMESPACE_URL, "version"),
        title="Oracle Cloud ADK 접속 문제 해결",
        source_path="knowledge/oracle-adk.md",
        heading_path=("문제 해결",),
        chunk_text="방화벽과 endpoint 설정을 확인했다.",
        metadata={"project": "second-brain"},
        score=0.03,
        matched_by=("keyword", "vector"),
        keyword_rank=1,
        vector_rank=2,
    )


def build_test_app():
    app = create_app()

    async def fake_session() -> object:
        return object()

    async def fake_provider() -> object:
        return object()

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_embedding_provider] = fake_provider
    return app


@pytest.mark.asyncio
async def test_query_api_returns_chunks_and_source_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_test_app()

    async def fake_execute_query(*_: object) -> list[SearchResult]:
        return [result()]

    monkeypatch.setattr(query_api, "execute_query", fake_execute_query)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/query",
            json={"query": "Oracle ADK", "filters": {"project": "second-brain", "limit": 5}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "Oracle ADK"
    assert payload["results"][0]["text"] == "방화벽과 endpoint 설정을 확인했다."
    assert payload["results"][0]["matched_by"] == ["keyword", "vector"]
    assert payload["results"][0]["source"] == {
        "document_id": str(result().document_id),
        "document_version_id": str(result().document_version_id),
        "chunk_id": str(result().chunk_id),
        "title": "Oracle Cloud ADK 접속 문제 해결",
        "source_path": "knowledge/oracle-adk.md",
        "heading_path": ["문제 해결"],
        "metadata": {"project": "second-brain"},
    }


@pytest.mark.asyncio
async def test_query_api_returns_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_test_app()

    async def no_results(*_: object) -> list[SearchResult]:
        return []

    monkeypatch.setattr(query_api, "execute_query", no_results)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/query", json={"query": "unknown"})

    assert response.status_code == 200
    assert response.json() == {"query": "unknown", "results": []}


@pytest.mark.asyncio
async def test_query_api_validates_request() -> None:
    app = build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        blank = await client.post("/api/v1/query", json={"query": " "})
        invalid_limit = await client.post(
            "/api/v1/query",
            json={"query": "valid", "filters": {"limit": 0}},
        )

    assert blank.status_code == 422
    assert invalid_limit.status_code == 422


@pytest.mark.asyncio
async def test_query_api_maps_embedding_failure_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_test_app()

    async def unavailable(*_: object) -> list[SearchResult]:
        raise EmbeddingError("Ollama unavailable")

    monkeypatch.setattr(query_api, "execute_query", unavailable)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/query", json={"query": "Oracle ADK"})

    assert response.status_code == 503
    assert response.json() == {"detail": "retrieval service unavailable"}
