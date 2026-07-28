import uuid

from app.modules.agent.domain.answer import AnswerSource, ToolTrace


def source(name: str) -> AnswerSource:
    return AnswerSource(
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, f"document:{name}"),
        document_version_id=uuid.uuid5(uuid.NAMESPACE_URL, f"version:{name}"),
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"chunk:{name}"),
        title=f"문서 {name}",
        section="개요",
        source_path=f"knowledge/{name}.md",
        source_reference=None,
        score=0.03,
    )


def test_tool_trace_deduplicates_sources_and_summarizes_calls() -> None:
    trace = ToolTrace()
    first = source("first")
    second = source("second")

    trace.record(
        route="hybrid",
        candidate_count=5,
        selected_sources=[first, second],
    )
    trace.record(
        route="hybrid",
        candidate_count=3,
        selected_sources=[first],
    )

    assert trace.called is True
    assert trace.sources == (first, second)
    assert trace.summary.route == "hybrid"
    assert trace.summary.candidate_count == 8
    assert trace.summary.selected_count == 2
    assert trace.summary.blocked_by_policy is False


def test_tool_trace_policy_block_is_sticky_and_financial_route_wins() -> None:
    trace = ToolTrace()

    trace.record(route="hybrid", candidate_count=1, selected_sources=[source("allowed")])
    trace.block(route="financial_hybrid", candidate_count=2)
    trace.record(
        route="hybrid",
        candidate_count=1,
        selected_sources=[source("ignored-after-block")],
    )

    assert trace.blocked_by_policy is True
    assert trace.sources == ()
    assert trace.summary.route == "financial_hybrid"
    assert trace.summary.candidate_count == 4
    assert trace.summary.selected_count == 0
