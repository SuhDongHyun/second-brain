from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

Route = Literal["hybrid", "financial_hybrid"]
POLICY_BLOCKED_ANSWER = (
    "관련 자료는 존재하지만 local_only 정책으로 인해 외부 모델을 통한 답변을 생성할 수 없습니다."
)


class AgentUnavailableError(RuntimeError):
    """Represent an unavailable model or retrieval dependency."""


class AgentProtocolError(RuntimeError):
    """Represent an incomplete agent turn that lacks required evidence or text."""


@dataclass(frozen=True, slots=True)
class AnswerSource:
    """Identify one knowledge chunk exposed to the answer model.
    The fields preserve exact document provenance without ORM dependencies."""

    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    title: str
    section: str
    source_path: str
    source_reference: str | None
    score: float


@dataclass(frozen=True, slots=True)
class RetrievalSummary:
    """Summarize Tool activity associated with one generated answer.
    Candidate and selected counts remain distinct for later provenance work."""

    route: Route
    candidate_count: int
    selected_count: int
    blocked_by_policy: bool


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    """Represent a grounded answer independently of its delivery interface.
    Provider metadata accompanies sources and retrieval diagnostics."""

    conversation_id: str
    answer: str
    sources: tuple[AnswerSource, ...]
    retrieval: RetrievalSummary
    provider: str
    model: str


@dataclass(slots=True)
class ToolTrace:
    """Accumulate request-local Retriever Tool activity and safe sources.
    Policy blocking is sticky and clears sources that must not leave the service."""

    _called: bool = False
    _blocked_by_policy: bool = False
    _route: Route = "hybrid"
    _candidate_count: int = 0
    _sources: dict[UUID, AnswerSource] = field(default_factory=dict)

    def record(
        self,
        *,
        route: Route,
        candidate_count: int,
        selected_sources: list[AnswerSource],
    ) -> None:
        """Record one successful Tool call and its selected sources.
        Financial routing takes precedence when multiple Tool types are invoked."""
        self._called = True
        self._candidate_count += candidate_count
        if route == "financial_hybrid":
            self._route = route
        if self._blocked_by_policy:
            return
        for source in selected_sources:
            self._sources.setdefault(source.chunk_id, source)

    def block(self, *, route: Route, candidate_count: int) -> None:
        """Mark the request as unsafe for external context transmission.
        Existing safe sources are cleared so mixed-policy results cannot escape."""
        self._called = True
        self._blocked_by_policy = True
        self._candidate_count += candidate_count
        if route == "financial_hybrid":
            self._route = route
        self._sources.clear()

    @property
    def called(self) -> bool:
        """Return whether any Retriever Tool was invoked."""
        return self._called

    @property
    def blocked_by_policy(self) -> bool:
        """Return whether a Tool encountered local-only knowledge."""
        return self._blocked_by_policy

    @property
    def sources(self) -> tuple[AnswerSource, ...]:
        """Return selected sources in stable first-seen order."""
        return tuple(self._sources.values())

    @property
    def summary(self) -> RetrievalSummary:
        """Build the immutable retrieval summary for the public answer."""
        return RetrievalSummary(
            route=self._route,
            candidate_count=self._candidate_count,
            selected_count=len(self._sources),
            blocked_by_policy=self._blocked_by_policy,
        )


class AgentTools(Protocol):
    """Describe the two async Function Tools available to the ADK agent."""

    @property
    def blocked_by_policy(self) -> bool:
        """Return whether the current turn encountered local-only knowledge."""
        ...

    async def search_knowledge(
        self,
        query: str,
        domain: str | None = None,
        project: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        latest: bool = False,
    ) -> dict[str, object]:
        """Search general knowledge using optional model-supplied filters."""
        ...

    async def query_financial_facts(
        self,
        company: str,
        metric: str | None = None,
        latest: bool = True,
        consolidated: bool = True,
    ) -> dict[str, object]:
        """Search OpenDART Markdown for financial evidence."""
        ...


class AgentRunner(Protocol):
    """Run one grounded agent turn with request-scoped Retriever Tools."""

    async def run(
        self,
        question: str,
        conversation_id: str,
        tools: AgentTools,
    ) -> str:
        """Return the final model text produced for one conversation turn."""
        ...
