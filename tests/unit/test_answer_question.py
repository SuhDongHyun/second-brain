import uuid

import pytest

from app.modules.agent.domain.answer import (
    AgentProtocolError,
    AgentUnavailableError,
    AnswerSource,
    ToolTrace,
)
from app.modules.agent.service.answer_question import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    POLICY_BLOCKED_ANSWER,
    answer_question,
)


class FakeRunner:
    def __init__(self, answer: str = "근거 기반 답변") -> None:
        self.answer = answer
        self.calls: list[tuple[str, str, object]] = []
        self.error: Exception | None = None

    async def run(self, question: str, conversation_id: str, tools: object) -> str:
        self.calls.append((question, conversation_id, tools))
        if self.error is not None:
            raise self.error
        return self.answer


def source() -> AnswerSource:
    return AnswerSource(
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, "document"),
        document_version_id=uuid.uuid5(uuid.NAMESPACE_URL, "version"),
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, "chunk"),
        title="근거 문서",
        section="개요",
        source_path="knowledge/source.md",
        source_reference="receipt-1",
        score=0.03,
    )


@pytest.mark.asyncio
async def test_answer_question_builds_domain_answer_from_trace() -> None:
    trace = ToolTrace()
    trace.record(route="hybrid", candidate_count=3, selected_sources=[source()])
    runner = FakeRunner()
    tools = object()

    answer = await answer_question(
        question="  질문  ",
        conversation_id="conversation-1",
        runner=runner,  # type: ignore[arg-type]
        tools=tools,  # type: ignore[arg-type]
        trace=trace,
        model="gemma-test",
    )

    assert runner.calls == [("질문", "conversation-1", tools)]
    assert answer.answer == "근거 기반 답변"
    assert answer.sources == (source(),)
    assert answer.retrieval.candidate_count == 3
    assert answer.provider == "google_adk"
    assert answer.model == "gemma-test"


@pytest.mark.asyncio
async def test_answer_question_overrides_model_text_when_policy_blocks() -> None:
    trace = ToolTrace()
    trace.block(route="hybrid", candidate_count=2)

    answer = await answer_question(
        question="민감한 질문",
        conversation_id="conversation-1",
        runner=FakeRunner("모델이 임의로 쓴 답변"),  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
        trace=trace,
        model="gemma-test",
    )

    assert answer.answer == POLICY_BLOCKED_ANSWER
    assert answer.sources == ()
    assert answer.retrieval.blocked_by_policy is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(" "),
        FakeRunner(),
    ],
)
async def test_answer_question_returns_policy_response_despite_model_failure(
    runner: FakeRunner,
) -> None:
    trace = ToolTrace()
    trace.block(route="hybrid", candidate_count=1)
    if runner.answer != " ":
        runner.error = RuntimeError("provider failed after blocked Tool result")

    answer = await answer_question(
        question="민감한 질문",
        conversation_id="conversation-1",
        runner=runner,  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
        trace=trace,
        model="gemma-test",
    )

    assert answer.answer == POLICY_BLOCKED_ANSWER
    assert answer.retrieval.blocked_by_policy is True


@pytest.mark.asyncio
async def test_answer_question_requires_tool_call_and_final_text() -> None:
    with pytest.raises(AgentProtocolError, match="Retriever Tool"):
        await answer_question(
            question="질문",
            conversation_id="conversation-1",
            runner=FakeRunner(),  # type: ignore[arg-type]
            tools=object(),  # type: ignore[arg-type]
            trace=ToolTrace(),
            model="gemma-test",
        )

    trace = ToolTrace()
    trace.record(route="hybrid", candidate_count=1, selected_sources=[source()])
    with pytest.raises(AgentProtocolError, match="final answer"):
        await answer_question(
            question="질문",
            conversation_id="conversation-1",
            runner=FakeRunner(" "),  # type: ignore[arg-type]
            tools=object(),  # type: ignore[arg-type]
            trace=trace,
            model="gemma-test",
        )


@pytest.mark.asyncio
async def test_answer_question_replaces_ungrounded_text_when_no_sources_exist() -> None:
    trace = ToolTrace()
    trace.record(route="hybrid", candidate_count=0, selected_sources=[])

    answer = await answer_question(
        question="자료가 없는 질문",
        conversation_id="conversation-1",
        runner=FakeRunner("모델의 사전지식 답변"),  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
        trace=trace,
        model="gemma-test",
    )

    assert answer.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert answer.sources == ()


@pytest.mark.asyncio
async def test_answer_question_maps_unexpected_runner_failure() -> None:
    runner = FakeRunner()
    runner.error = RuntimeError("provider internals")

    with pytest.raises(AgentUnavailableError, match="unavailable"):
        await answer_question(
            question="질문",
            conversation_id="conversation-1",
            runner=runner,  # type: ignore[arg-type]
            tools=object(),  # type: ignore[arg-type]
            trace=ToolTrace(),
            model="gemma-test",
        )
