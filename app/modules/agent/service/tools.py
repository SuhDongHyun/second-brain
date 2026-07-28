from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.domain.answer import AnswerSource, Route, ToolTrace
from app.modules.knowledge.domain.retrieval import SearchFilters, SearchResult
from app.modules.knowledge.infra.embedding import EmbeddingProvider
from app.modules.knowledge.service.chunk_markdown import estimate_tokens
from app.modules.knowledge.service.search_knowledge import hybrid_search

Search = Callable[
    [str, AsyncSession, EmbeddingProvider, SearchFilters],
    Awaitable[list[SearchResult]],
]

INVALID_FILTERS = {
    "status": "invalid_request",
    "error": "tool filters conflict with request filters",
}
INVALID_ARGUMENTS = {
    "status": "invalid_request",
    "error": "invalid tool arguments",
}
LATEST_CANDIDATE_LIMIT = 50
MAX_TOOL_CALLS_PER_TURN = 4


@dataclass(frozen=True, slots=True)
class RetrieverTools:
    """Expose request-scoped Hybrid Retrieval as ADK-compatible async methods.
    The boundary applies caller filters, context limits, and external-LLM policy."""

    session: AsyncSession
    embedding_provider: EmbeddingProvider
    request_filters: SearchFilters
    trace: ToolTrace
    max_context_tokens: int
    max_results: int
    search: Search
    _search_lock: asyncio.Lock = dataclass_field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
        compare=False,
    )
    _remaining_context_tokens: int = dataclass_field(init=False, repr=False, compare=False)
    _remaining_results: int = dataclass_field(init=False, repr=False, compare=False)
    _remaining_tool_calls: int = dataclass_field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Initialize mutable request budgets inside the frozen dependency object."""
        object.__setattr__(self, "_remaining_context_tokens", self.max_context_tokens)
        object.__setattr__(self, "_remaining_results", self.max_results)
        object.__setattr__(self, "_remaining_tool_calls", MAX_TOOL_CALLS_PER_TURN)

    @property
    def blocked_by_policy(self) -> bool:
        """Expose policy state so ADK can skip its post-Tool model call."""
        return self.trace.blocked_by_policy

    async def search_knowledge(
        self,
        query: str,
        domain: str | None = None,
        project: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        latest: bool = False,
    ) -> dict[str, object]:
        """Search general knowledge without widening request-level filters.
        Only policy-approved and context-bounded chunks are returned to ADK."""
        normalized_query = query.strip()
        if not normalized_query:
            return INVALID_ARGUMENTS.copy()
        try:
            filters = self._effective_filters(
                domain=domain,
                project=project,
                date_from=date_from,
                date_to=date_to,
            )
        except ValueError as exc:
            if str(exc) == "filter conflict":
                return INVALID_FILTERS.copy()
            return INVALID_ARGUMENTS.copy()
        return await self._run(
            query=normalized_query,
            filters=filters,
            route="hybrid",
            latest=latest,
        )

    async def query_financial_facts(
        self,
        company: str,
        metric: str | None = None,
        latest: bool = True,
        consolidated: bool = True,
    ) -> dict[str, object]:
        """Search OpenDART Markdown for grounded financial evidence.
        The Tool performs retrieval only and never claims SQL-backed aggregation."""
        normalized_company = company.strip()
        normalized_metric = metric.strip() if metric is not None else None
        if not normalized_company or metric is not None and not normalized_metric:
            return INVALID_ARGUMENTS.copy()
        try:
            filters = self._effective_filters(
                domain="finance",
                project=None,
                date_from=None,
                date_to=None,
                source_type="opendart",
            )
        except ValueError as exc:
            if str(exc) == "filter conflict":
                return INVALID_FILTERS.copy()
            return INVALID_ARGUMENTS.copy()

        parts = [normalized_company]
        if normalized_metric:
            parts.append(normalized_metric)
        if latest:
            parts.append("가장 최근")
        parts.append("연결재무제표 (CFS)" if consolidated else "별도재무제표 (OFS)")
        return await self._run(
            query=" ".join(parts),
            filters=filters,
            route="financial_hybrid",
            latest=latest,
        )

    def _effective_filters(
        self,
        *,
        domain: str | None,
        project: str | None,
        date_from: str | None,
        date_to: str | None,
        source_type: str | None = None,
    ) -> SearchFilters:
        """Intersect model-supplied filters with immutable request constraints.
        Conflicting scalar values are rejected instead of silently widening scope."""
        request = self.request_filters
        effective_domain = _intersect_scalar(request.domain, domain)
        effective_project = _intersect_scalar(request.project, project)
        effective_source_type = _intersect_scalar(request.source_type, source_type)
        tool_from = _parse_datetime(date_from)
        tool_to = _parse_datetime(date_to)
        updated_from = _later(request.updated_from, tool_from)
        updated_to = _earlier(request.updated_to, tool_to)
        return SearchFilters(
            project=effective_project,
            domain=effective_domain,
            source_type=effective_source_type,
            document_type=request.document_type,
            tags=list(request.tags),
            updated_from=updated_from,
            updated_to=updated_to,
            limit=min(request.limit, self.max_results),
        )

    async def _run(
        self,
        *,
        query: str,
        filters: SearchFilters,
        route: Route,
        latest: bool,
    ) -> dict[str, object]:
        """Execute Hybrid Retrieval and serialize a policy-safe bounded context.
        Trace updates occur before returning so the API can report Tool activity."""
        async with self._search_lock:
            if (
                self._remaining_tool_calls < 1
                or self._remaining_context_tokens < 1
                or self._remaining_results < 1
            ):
                return {"status": "budget_exhausted", "results": []}
            object.__setattr__(
                self,
                "_remaining_tool_calls",
                self._remaining_tool_calls - 1,
            )
            search_filters = replace(filters, limit=LATEST_CANDIDATE_LIMIT) if latest else filters
            results = await self.search(
                query,
                self.session,
                self.embedding_provider,
                search_filters,
            )
            candidate_count = len(results)
            if any(result.metadata.get("llm_policy") == "local_only" for result in results):
                self.trace.block(route=route, candidate_count=candidate_count)
                return {"status": "blocked_by_policy"}

            ranked = _sort_latest(results) if latest else results
            selected = _select_context(
                ranked,
                max_results=min(filters.limit, self._remaining_results),
                max_context_tokens=self._remaining_context_tokens,
            )
            used_tokens = sum(estimate_tokens(result.chunk_text) for result in selected)
            object.__setattr__(
                self,
                "_remaining_context_tokens",
                self._remaining_context_tokens - used_tokens,
            )
            object.__setattr__(
                self,
                "_remaining_results",
                self._remaining_results - len(selected),
            )
            sources = [_to_source(result) for result in selected]
            self.trace.record(
                route=route,
                candidate_count=candidate_count,
                selected_sources=sources,
            )
            if not selected:
                return {"status": "no_results", "results": []}
            return {
                "status": "ok",
                "results": [_serialize_result(result) for result in selected],
            }


def create_retriever_tools(
    *,
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
    request_filters: SearchFilters,
    trace: ToolTrace,
    max_context_tokens: int,
    max_results: int,
    search: Search = hybrid_search,
) -> RetrieverTools:
    """Build request-local Retriever Tools with explicit infrastructure dependencies.
    Bounds are validated before the methods can be exposed to an agent."""
    if max_context_tokens < 1:
        raise ValueError("max_context_tokens must be positive")
    if not 1 <= max_results <= 8:
        raise ValueError("max_results must be between 1 and 8")
    return RetrieverTools(
        session=session,
        embedding_provider=embedding_provider,
        request_filters=request_filters,
        trace=trace,
        max_context_tokens=max_context_tokens,
        max_results=max_results,
        search=search,
    )


def _intersect_scalar(request_value: str | None, tool_value: str | None) -> str | None:
    """Return the narrower scalar value or reject conflicting constraints."""
    normalized_tool = tool_value.strip() if tool_value is not None else None
    if tool_value is not None and not normalized_tool:
        raise ValueError("invalid scalar filter")
    if (
        request_value is not None
        and normalized_tool is not None
        and request_value != normalized_tool
    ):
        raise ValueError("filter conflict")
    return request_value or normalized_tool


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse a timezone-aware ISO timestamp supplied by an agent Tool call."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return parsed


def _later(first: datetime | None, second: datetime | None) -> datetime | None:
    """Return the later non-null lower bound."""
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _earlier(first: datetime | None, second: datetime | None) -> datetime | None:
    """Return the earlier non-null upper bound."""
    if first is None:
        return second
    if second is None:
        return first
    return min(first, second)


def _sort_latest(results: list[SearchResult]) -> list[SearchResult]:
    """Prefer stable document update timestamps while preserving fused rank ties."""

    def sort_key(item: SearchResult) -> tuple[float, float]:
        value = item.metadata.get("updated_at")
        try:
            timestamp = datetime.fromisoformat(str(value)).timestamp()
        except (TypeError, ValueError):
            timestamp = float("-inf")
        return (-timestamp, -item.score)

    return sorted(results, key=sort_key)


def _select_context(
    results: list[SearchResult],
    *,
    max_results: int,
    max_context_tokens: int,
) -> list[SearchResult]:
    """Choose complete chunks without exceeding result or token limits."""
    selected: list[SearchResult] = []
    token_count = 0
    for result in results:
        result_tokens = estimate_tokens(result.chunk_text)
        if token_count + result_tokens > max_context_tokens:
            continue
        selected.append(result)
        token_count += result_tokens
        if len(selected) == max_results:
            break
    return selected


def _to_source(result: SearchResult) -> AnswerSource:
    """Convert one retrieval result into the stable answer source contract."""
    return AnswerSource(
        document_id=result.document_id,
        document_version_id=result.document_version_id,
        chunk_id=result.chunk_id,
        title=result.title,
        section=" > ".join(result.heading_path),
        source_path=result.source_path,
        source_reference=_source_reference(result),
        score=result.score,
    )


def _source_reference(result: SearchResult) -> str | None:
    """Return an OpenDART receipt number when the source provides one."""
    value = result.metadata.get("receipt_number")
    return str(value) if value is not None else None


def _serialize_result(result: SearchResult) -> dict[str, object]:
    """Serialize only context and provenance fields approved for external use."""
    return {
        "document_id": str(result.document_id),
        "document_version_id": str(result.document_version_id),
        "chunk_id": str(result.chunk_id),
        "text": result.chunk_text,
        "title": result.title,
        "heading_path": list(result.heading_path),
        "source_path": result.source_path,
        "source_reference": _source_reference(result),
        "score": result.score,
    }
