import uuid

import httpx
import pytest

import app.modules.knowledge.interface.controller as answer_api
from app.config import AdkSettings
from app.db import get_session
from app.main import create_app
from app.modules.agent.domain.answer import (
    AgentAnswer,
    AgentProtocolError,
    AgentUnavailableError,
    AnswerSource,
    RetrievalSummary,
)
from app.modules.knowledge.interface.controller import (
    execute_agent_query,
    get_adk_settings,
    get_agent_runner,
    get_embedding_provider,
)
from app.modules.knowledge.interface.schema import AgentQueryRequest


def settings() -> AdkSettings:
    return AdkSettings(
        api_key="test-key",
        model="gemma-test",
        timeout_seconds=5,
        app_name="second_brain",
        user_id="service_user",
        max_context_tokens=6000,
        max_results=6,
    )


def answer(conversation_id: str) -> AgentAnswer:
    return AgentAnswer(
        conversation_id=conversation_id,
        answer="근거 기반 답변",
        sources=(
            AnswerSource(
                document_id=uuid.uuid5(uuid.NAMESPACE_URL, "document"),
                document_version_id=uuid.uuid5(uuid.NAMESPACE_URL, "version"),
                chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, "chunk"),
                title="근거 문서",
                section="개요",
                source_path="knowledge/source.md",
                source_reference="receipt-1",
                score=0.03,
            ),
        ),
        retrieval=RetrievalSummary(
            route="hybrid",
            candidate_count=3,
            selected_count=1,
            blocked_by_policy=False,
        ),
        provider="google_adk",
        model="gemma-test",
    )


def build_test_app():
    app = create_app()

    async def fake_session() -> object:
        return object()

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_embedding_provider] = lambda: object()
    app.dependency_overrides[get_agent_runner] = lambda: object()
    app.dependency_overrides[get_adk_settings] = settings
    return app


@pytest.mark.asyncio
async def test_execute_agent_query_wires_request_scoped_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    tools = object()
    expected = answer("conversation-1")

    def fake_create_tools(**kwargs: object) -> object:
        captured["tools"] = kwargs
        return tools

    async def fake_answer_question(**kwargs: object) -> AgentAnswer:
        captured["answer"] = kwargs
        return expected

    monkeypatch.setattr(answer_api, "create_retriever_tools", fake_create_tools)
    monkeypatch.setattr(answer_api, "answer_question", fake_answer_question)
    session = object()
    embedding_provider = object()
    runner = object()

    result = await execute_agent_query(
        payload=AgentQueryRequest(
            question="질문",
            filters={"project": "second-brain", "limit": 4},
        ),
        conversation_id="conversation-1",
        session=session,  # type: ignore[arg-type]
        embedding_provider=embedding_provider,  # type: ignore[arg-type]
        runner=runner,  # type: ignore[arg-type]
        settings=settings(),
    )

    assert result is expected
    tool_kwargs = captured["tools"]
    assert tool_kwargs["session"] is session  # type: ignore[index]
    assert tool_kwargs["embedding_provider"] is embedding_provider  # type: ignore[index]
    assert tool_kwargs["request_filters"].project == "second-brain"  # type: ignore[index,union-attr]
    assert tool_kwargs["request_filters"].limit == 4  # type: ignore[index,union-attr]
    assert tool_kwargs["max_context_tokens"] == 6000  # type: ignore[index]
    assert tool_kwargs["max_results"] == 6  # type: ignore[index]
    answer_kwargs = captured["answer"]
    assert answer_kwargs["question"] == "질문"  # type: ignore[index]
    assert answer_kwargs["conversation_id"] == "conversation-1"  # type: ignore[index]
    assert answer_kwargs["runner"] is runner  # type: ignore[index]
    assert answer_kwargs["tools"] is tools  # type: ignore[index]
    assert answer_kwargs["trace"] is tool_kwargs["trace"]  # type: ignore[index]
    assert answer_kwargs["model"] == "gemma-test"  # type: ignore[index]


@pytest.mark.asyncio
async def test_agent_query_api_returns_grounded_answer_and_generated_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_test_app()
    captured: dict[str, object] = {}

    async def fake_execute(**kwargs: object) -> AgentAnswer:
        captured.update(kwargs)
        return answer(str(kwargs["conversation_id"]))

    monkeypatch.setattr(answer_api, "execute_agent_query", fake_execute)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/query",
            json={
                "question": " Oracle ADK 해결 방법 ",
                "filters": {"project": "second-brain", "limit": 6},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    uuid.UUID(payload["conversation_id"])
    assert captured["conversation_id"] == payload["conversation_id"]
    assert payload == {
        "conversation_id": payload["conversation_id"],
        "answer": "근거 기반 답변",
        "sources": [
            {
                "document_id": str(answer("x").sources[0].document_id),
                "document_version_id": str(answer("x").sources[0].document_version_id),
                "chunk_id": str(answer("x").sources[0].chunk_id),
                "title": "근거 문서",
                "section": "개요",
                "source_path": "knowledge/source.md",
                "source_reference": "receipt-1",
                "score": 0.03,
            }
        ],
        "retrieval": {
            "route": "hybrid",
            "candidate_count": 3,
            "selected_count": 1,
            "blocked_by_policy": False,
        },
        "model": {"provider": "google_adk", "name": "gemma-test"},
    }


@pytest.mark.asyncio
async def test_agent_query_api_reuses_supplied_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_test_app()

    async def fake_execute(**kwargs: object) -> AgentAnswer:
        return answer(str(kwargs["conversation_id"]))

    monkeypatch.setattr(answer_api, "execute_agent_query", fake_execute)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/query",
            json={"question": "질문", "conversation_id": "conversation-1"},
        )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == "conversation-1"


@pytest.mark.asyncio
async def test_agent_query_api_validates_question_conversation_and_limit() -> None:
    app = build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        blank_question = await client.post("/api/query", json={"question": " "})
        blank_conversation = await client.post(
            "/api/query",
            json={"question": "질문", "conversation_id": " "},
        )
        invalid_limit = await client.post(
            "/api/query",
            json={"question": "질문", "filters": {"limit": 9}},
        )
        oversized_conversation = await client.post(
            "/api/query",
            json={"question": "질문", "conversation_id": "x" * 129},
        )
        oversized_question = await client.post(
            "/api/query",
            json={"question": "x" * 4001},
        )

    assert blank_question.status_code == 422
    assert blank_conversation.status_code == 422
    assert invalid_limit.status_code == 422
    assert oversized_conversation.status_code == 422
    assert oversized_question.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (AgentUnavailableError("unavailable"), 503),
        (AgentProtocolError("invalid final event"), 502),
    ],
)
async def test_agent_query_api_maps_service_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
) -> None:
    app = build_test_app()

    async def fail(**_: object) -> AgentAnswer:
        raise error

    monkeypatch.setattr(answer_api, "execute_agent_query", fail)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/query", json={"question": "질문"})

    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_versioned_query_alias_is_not_exposed() -> None:
    app = build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/query", json={"question": "질문"})

    assert response.status_code == 404
