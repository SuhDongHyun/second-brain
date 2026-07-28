from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.knowledge.domain.retrieval import SearchFilters


class QueryFilters(BaseModel):
    """Validate optional filter fields accepted by the query endpoint.
    Domain construction supplies cross-field validation beyond HTTP constraints."""

    project: str | None = None
    domain: str | None = None
    source_type: str | None = None
    document_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def validate_as_domain(self) -> QueryFilters:
        """Run domain filter validation while parsing the HTTP payload.
        The interface model is returned unchanged after successful construction."""
        SearchFilters(**self.model_dump())
        return self

    def to_domain(self) -> SearchFilters:
        """Convert validated HTTP filters into the domain search value.
        The explicit mapping prevents Pydantic models from leaking into services."""
        return SearchFilters(**self.model_dump())


class QueryRequest(BaseModel):
    """Describe a knowledge query and its optional retrieval filters.
    Query text is normalized before the controller invokes the search service."""

    query: str = Field(min_length=1)
    filters: QueryFilters = Field(default_factory=QueryFilters)

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        """Strip query whitespace and reject an empty search request.
        Downstream embedding and retrieval therefore receive canonical text."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized


class SourceResponse(BaseModel):
    """Expose document and chunk provenance for one query result.
    Identifiers and metadata let clients trace the exact supporting source."""

    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    title: str
    source_path: str
    heading_path: tuple[str, ...]
    metadata: dict[str, Any]


class QueryResultResponse(BaseModel):
    """Expose one fused result with scoring and supporting source details.
    Channel ranks explain how keyword and vector retrieval matched the text."""

    score: float
    matched_by: tuple[Literal["keyword", "vector"], ...]
    keyword_rank: int | None
    vector_rank: int | None
    text: str
    source: SourceResponse


class QueryResponse(BaseModel):
    """Wrap the normalized query and its ordered retrieval results.
    The stable envelope supports empty and populated evidence responses."""

    query: str
    results: list[QueryResultResponse]
