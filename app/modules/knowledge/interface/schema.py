from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.agent.domain.answer import AgentAnswer
from app.modules.knowledge.domain.retrieval import SearchFilters


class AgentQueryFilters(BaseModel):
    """Validate bounded retrieval filters for generated answers.
    Domain construction enforces date ordering and normalized scalar values."""

    project: str | None = None
    domain: str | None = None
    source_type: str | None = None
    document_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    limit: int = Field(default=6, ge=1, le=8)

    @model_validator(mode="after")
    def validate_as_domain(self) -> AgentQueryFilters:
        """Validate cross-field rules through the framework-free domain value."""
        SearchFilters(**self.model_dump())
        return self

    def to_domain(self) -> SearchFilters:
        """Convert HTTP filters into the knowledge retrieval domain value."""
        return SearchFilters(**self.model_dump())


class AgentQueryRequest(BaseModel):
    """Describe a question, optional conversation, and retrieval constraints."""

    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=128)
    filters: AgentQueryFilters = Field(default_factory=AgentQueryFilters)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        """Trim question text and reject whitespace-only input."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized

    @field_validator("conversation_id")
    @classmethod
    def normalize_conversation_id(cls, value: str | None) -> str | None:
        """Trim a supplied conversation ID and reject an empty identifier."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("conversation_id must not be blank")
        return normalized


class AgentSourceResponse(BaseModel):
    """Expose one chunk source that was supplied to the answer model."""

    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    title: str
    section: str
    source_path: str
    source_reference: str | None
    score: float


class RetrievalSummaryResponse(BaseModel):
    """Expose Tool routing, candidate counts, and policy status."""

    route: Literal["hybrid", "financial_hybrid"]
    candidate_count: int
    selected_count: int
    blocked_by_policy: bool


class ModelResponse(BaseModel):
    """Identify the provider and configured answer model."""

    provider: str
    name: str


class AgentQueryResponse(BaseModel):
    """Return a grounded answer with source and retrieval diagnostics."""

    conversation_id: str
    answer: str
    sources: list[AgentSourceResponse]
    retrieval: RetrievalSummaryResponse
    model: ModelResponse

    @classmethod
    def from_domain(cls, answer: AgentAnswer) -> AgentQueryResponse:
        """Map an agent-independent answer into the public HTTP schema."""
        return cls(
            conversation_id=answer.conversation_id,
            answer=answer.answer,
            sources=[
                AgentSourceResponse(
                    document_id=source.document_id,
                    document_version_id=source.document_version_id,
                    chunk_id=source.chunk_id,
                    title=source.title,
                    section=source.section,
                    source_path=source.source_path,
                    source_reference=source.source_reference,
                    score=source.score,
                )
                for source in answer.sources
            ],
            retrieval=RetrievalSummaryResponse(
                route=answer.retrieval.route,
                candidate_count=answer.retrieval.candidate_count,
                selected_count=answer.retrieval.selected_count,
                blocked_by_policy=answer.retrieval.blocked_by_policy,
            ),
            model=ModelResponse(provider=answer.provider, name=answer.model),
        )
