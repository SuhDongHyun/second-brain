import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from app.modules.agent.domain.answer import ToolTrace
from app.modules.agent.service.tools import create_retriever_tools
from app.modules.knowledge.domain.retrieval import SearchFilters, SearchResult


def result(
    name: str,
    *,
    text: str | None = None,
    policy: str = "external_allowed",
    updated_at: str = "2026-07-28T00:00:00+00:00",
) -> SearchResult:
    return SearchResult(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"chunk:{name}"),
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, f"document:{name}"),
        document_version_id=uuid.uuid5(uuid.NAMESPACE_URL, f"version:{name}"),
        title=f"문서 {name}",
        source_path=f"knowledge/{name}.md",
        heading_path=("연결재무제표 (CFS)", "손익계산서"),
        chunk_text=text or f"본문 {name}",
        metadata={
            "llm_policy": policy,
            "receipt_number": f"receipt-{name}",
            "updated_at": updated_at,
            "private_value": "must-not-leak",
        },
        score=0.03,
        matched_by=("keyword", "vector"),
        keyword_rank=1,
        vector_rank=1,
    )


class SearchSpy:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, SearchFilters]] = []

    async def __call__(
        self,
        query: str,
        _session: object,
        _provider: object,
        filters: SearchFilters,
    ) -> list[SearchResult]:
        self.calls.append((query, filters))
        return self.results


class ConcurrentSearchSpy(SearchSpy):
    def __init__(self, results: list[SearchResult]) -> None:
        super().__init__(results)
        self.active = 0
        self.max_active = 0

    async def __call__(
        self,
        query: str,
        _session: object,
        _provider: object,
        filters: SearchFilters,
    ) -> list[SearchResult]:
        self.calls.append((query, filters))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return self.results


def tools_for(
    search: SearchSpy,
    *,
    filters: SearchFilters | None = None,
    trace: ToolTrace | None = None,
    max_context_tokens: int = 100,
    max_results: int = 6,
):
    return create_retriever_tools(
        session=object(),  # type: ignore[arg-type]
        embedding_provider=object(),  # type: ignore[arg-type]
        request_filters=filters or SearchFilters(limit=max_results),
        trace=trace or ToolTrace(),
        max_context_tokens=max_context_tokens,
        max_results=max_results,
        search=search,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_search_knowledge_intersects_request_and_tool_filters() -> None:
    search = SearchSpy([result("allowed")])
    tools = tools_for(
        search,
        filters=SearchFilters(
            project="second-brain",
            tags=["google-adk"],
            updated_from=datetime(2026, 7, 1, tzinfo=UTC),
            limit=6,
        ),
    )

    payload = await tools.search_knowledge(
        "  Oracle ADK  ",
        domain="development",
        project="second-brain",
        date_from="2026-07-15T00:00:00+00:00",
    )

    query, filters = search.calls[0]
    assert query == "Oracle ADK"
    assert filters.project == "second-brain"
    assert filters.domain == "development"
    assert filters.tags == ["google-adk"]
    assert filters.updated_from == datetime(2026, 7, 15, tzinfo=UTC)
    assert filters.limit == 6
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_search_knowledge_rejects_filter_widening_without_search() -> None:
    search = SearchSpy([result("unused")])
    tools = tools_for(search, filters=SearchFilters(project="second-brain"))

    payload = await tools.search_knowledge("query", project="another-project")

    assert payload == {
        "status": "invalid_request",
        "error": "tool filters conflict with request filters",
    }
    assert search.calls == []


@pytest.mark.asyncio
async def test_tools_reject_blank_arguments_and_invalid_date_ranges_without_search() -> None:
    search = SearchSpy([result("unused")])
    tools = tools_for(search)

    assert await tools.search_knowledge(" ") == {
        "status": "invalid_request",
        "error": "invalid tool arguments",
    }
    assert await tools.search_knowledge("query", project=" ") == {
        "status": "invalid_request",
        "error": "invalid tool arguments",
    }
    assert await tools.search_knowledge(
        "query",
        date_from="2026-07-29T00:00:00+00:00",
        date_to="2026-07-28T00:00:00+00:00",
    ) == {
        "status": "invalid_request",
        "error": "invalid tool arguments",
    }
    assert await tools.query_financial_facts(" ") == {
        "status": "invalid_request",
        "error": "invalid tool arguments",
    }
    assert await tools.query_financial_facts("삼성전자", metric=" ") == {
        "status": "invalid_request",
        "error": "invalid tool arguments",
    }
    assert search.calls == []


@pytest.mark.parametrize(
    ("max_context_tokens", "max_results", "message"),
    [
        (0, 6, "max_context_tokens"),
        (100, 0, "max_results"),
        (100, 9, "max_results"),
    ],
)
def test_retriever_tool_factory_rejects_invalid_bounds(
    max_context_tokens: int,
    max_results: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        tools_for(
            SearchSpy([]),
            filters=SearchFilters(limit=1),
            max_context_tokens=max_context_tokens,
            max_results=max_results,
        )


@pytest.mark.asyncio
async def test_financial_tool_forces_opendart_scope_and_statement_type() -> None:
    search = SearchSpy([result("finance")])
    tools = tools_for(search)

    payload = await tools.query_financial_facts(
        "삼성전자",
        metric="영업이익",
        latest=True,
        consolidated=False,
    )

    query, filters = search.calls[0]
    assert query == "삼성전자 영업이익 가장 최근 별도재무제표 (OFS)"
    assert filters.domain == "finance"
    assert filters.source_type == "opendart"
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_financial_tool_supports_default_metric_and_non_latest_cfs() -> None:
    search = SearchSpy([result("finance")])
    tools = tools_for(search)

    payload = await tools.query_financial_facts(
        "삼성전자",
        metric=None,
        latest=False,
        consolidated=True,
    )

    query, filters = search.calls[0]
    assert query == "삼성전자 연결재무제표 (CFS)"
    assert filters.domain == "finance"
    assert filters.source_type == "opendart"
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_tools_serialize_only_approved_context_and_trace_sources() -> None:
    trace = ToolTrace()
    search = SearchSpy([result("first")])
    tools = tools_for(search, trace=trace)

    payload = await tools.search_knowledge("query")

    item = payload["results"][0]  # type: ignore[index]
    assert item == {
        "document_id": str(result("first").document_id),
        "document_version_id": str(result("first").document_version_id),
        "chunk_id": str(result("first").chunk_id),
        "text": "본문 first",
        "title": "문서 first",
        "heading_path": ["연결재무제표 (CFS)", "손익계산서"],
        "source_path": "knowledge/first.md",
        "source_reference": "receipt-first",
        "score": 0.03,
    }
    assert "private_value" not in str(payload)
    assert trace.sources[0].source_reference == "receipt-first"


@pytest.mark.asyncio
async def test_tools_enforce_context_and_result_limits() -> None:
    trace = ToolTrace()
    search = SearchSpy(
        [
            result("too-large", text=" ".join(f"word{index}" for index in range(20))),
            result("first", text="one two three"),
            result("second", text="four five six"),
        ]
    )
    tools = tools_for(search, trace=trace, max_context_tokens=6, max_results=2)

    payload = await tools.search_knowledge("query")

    assert [item["title"] for item in payload["results"]] == [  # type: ignore[index]
        "문서 first",
        "문서 second",
    ]
    assert trace.summary.candidate_count == 3
    assert trace.summary.selected_count == 2


@pytest.mark.asyncio
async def test_tools_serialize_parallel_searches_on_one_async_session() -> None:
    search = ConcurrentSearchSpy([result("first")])
    tools = tools_for(search)

    first, second = await asyncio.gather(
        tools.search_knowledge("first query"),
        tools.search_knowledge("second query"),
    )

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert search.max_active == 1


@pytest.mark.asyncio
async def test_context_and_result_budgets_apply_to_the_whole_turn() -> None:
    search = SearchSpy(
        [
            result("first", text="one two three"),
            result("second", text="four five six"),
        ]
    )
    tools = tools_for(search, max_context_tokens=6, max_results=2)

    first = await tools.search_knowledge("first query")
    second = await tools.search_knowledge("second query")

    assert len(first["results"]) == 2
    assert second == {"status": "budget_exhausted", "results": []}


@pytest.mark.asyncio
async def test_latest_search_sorts_valid_timestamps_before_malformed_values() -> None:
    search = SearchSpy(
        [
            result("old", updated_at="2025-01-01T00:00:00+00:00"),
            result("invalid", updated_at="not-a-date"),
            result("new", updated_at="2026-01-01T00:00:00+00:00"),
            result("fourth", updated_at="2024-01-01T00:00:00+00:00"),
            result("fifth", updated_at="2023-01-01T00:00:00+00:00"),
            result("sixth", updated_at="2022-01-01T00:00:00+00:00"),
            result("newest", updated_at="2027-01-01T00:00:00+00:00"),
        ]
    )
    tools = tools_for(search)

    payload = await tools.search_knowledge("query", latest=True)

    assert search.calls[0][1].limit == 50
    assert len(payload["results"]) == 6
    assert payload["results"][0]["title"] == "문서 newest"  # type: ignore[index]
    assert payload["results"][-1]["title"] == "문서 sixth"  # type: ignore[index]


@pytest.mark.asyncio
async def test_any_local_only_result_blocks_all_context() -> None:
    trace = ToolTrace()
    secret = "절대 외부로 보내지 않을 민감 본문"
    search = SearchSpy(
        [
            result("allowed"),
            result("secret", text=secret, policy="local_only"),
        ]
    )
    tools = tools_for(search, trace=trace)

    payload = await tools.search_knowledge("query")

    assert payload == {"status": "blocked_by_policy"}
    assert secret not in str(payload)
    assert trace.blocked_by_policy is True
    assert trace.sources == ()


@pytest.mark.asyncio
async def test_empty_results_and_invalid_dates_are_stable_tool_responses() -> None:
    search = SearchSpy([])
    tools = tools_for(search)

    empty = await tools.search_knowledge("unknown")
    invalid = await tools.search_knowledge("query", date_from="not-a-date")

    assert empty == {"status": "no_results", "results": []}
    assert invalid == {
        "status": "invalid_request",
        "error": "invalid tool arguments",
    }
