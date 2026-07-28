from app.modules.agent.domain.answer import (
    POLICY_BLOCKED_ANSWER,
    AgentAnswer,
    AgentProtocolError,
    AgentRunner,
    AgentTools,
    AgentUnavailableError,
    ToolTrace,
)

INSUFFICIENT_EVIDENCE_ANSWER = "검색된 근거가 부족하여 답변을 생성할 수 없습니다."


async def answer_question(
    *,
    question: str,
    conversation_id: str,
    runner: AgentRunner,
    tools: AgentTools,
    trace: ToolTrace,
    model: str,
) -> AgentAnswer:
    """Run one grounded agent turn and construct its public domain result.
    Tool trace data remains authoritative for sources and policy decisions."""
    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("question must not be blank")
    try:
        generated_text = await runner.run(
            normalized_question,
            conversation_id,
            tools,
        )
    except (AgentUnavailableError, AgentProtocolError):
        if trace.blocked_by_policy:
            return _policy_blocked_answer(conversation_id, trace, model)
        if trace.called and not trace.sources:
            return _insufficient_evidence_answer(conversation_id, trace, model)
        raise
    except Exception as exc:
        if trace.blocked_by_policy:
            return _policy_blocked_answer(conversation_id, trace, model)
        if trace.called and not trace.sources:
            return _insufficient_evidence_answer(conversation_id, trace, model)
        raise AgentUnavailableError("answer service unavailable") from exc

    if not trace.called:
        raise AgentProtocolError("agent did not call a Retriever Tool")
    if trace.blocked_by_policy:
        return _policy_blocked_answer(conversation_id, trace, model)
    if not trace.sources:
        return _insufficient_evidence_answer(conversation_id, trace, model)
    normalized_answer = generated_text.strip()
    if not normalized_answer:
        raise AgentProtocolError("agent did not return a final answer")
    return AgentAnswer(
        conversation_id=conversation_id,
        answer=normalized_answer,
        sources=trace.sources,
        retrieval=trace.summary,
        provider="google_adk",
        model=model,
    )


def _policy_blocked_answer(
    conversation_id: str,
    trace: ToolTrace,
    model: str,
) -> AgentAnswer:
    """Build the application-owned response without trusting another model turn."""
    return AgentAnswer(
        conversation_id=conversation_id,
        answer=POLICY_BLOCKED_ANSWER,
        sources=(),
        retrieval=trace.summary,
        provider="google_adk",
        model=model,
    )


def _insufficient_evidence_answer(
    conversation_id: str,
    trace: ToolTrace,
    model: str,
) -> AgentAnswer:
    """Build an application-owned response when retrieval supplied no evidence."""
    return AgentAnswer(
        conversation_id=conversation_id,
        answer=INSUFFICIENT_EVIDENCE_ANSWER,
        sources=(),
        retrieval=trace.summary,
        provider="google_adk",
        model=model,
    )
