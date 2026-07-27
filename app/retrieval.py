from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Select, func, literal, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings import EmbeddingProvider
from app.models import Chunk, Document, DocumentVersion

EMBEDDING_DIMENSIONS = 1024


class SearchFilters(BaseModel):
    project: str | None = None
    domain: str | None = None
    source_type: str | None = None
    document_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("project", "domain", "source_type", "document_type")
    @classmethod
    def reject_blank_filter(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("filter values must not be blank")
        return normalized

    @field_validator("tags")
    @classmethod
    def reject_blank_tags(cls, value: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in value]
        if any(not tag for tag in normalized):
            raise ValueError("tags must not contain blank values")
        return normalized

    @model_validator(mode="after")
    def validate_date_range(self) -> SearchFilters:
        for value in (self.updated_from, self.updated_to):
            if value is not None and value.utcoffset() is None:
                raise ValueError("date filters must be timezone-aware")
        if (
            self.updated_from is not None
            and self.updated_to is not None
            and self.updated_from > self.updated_to
        ):
            raise ValueError("updated_from must not be after updated_to")
        return self


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    title: str
    source_path: str
    heading_path: tuple[str, ...]
    chunk_text: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    title: str
    source_path: str
    heading_path: tuple[str, ...]
    chunk_text: str
    metadata: dict[str, Any]
    score: float
    matched_by: tuple[Literal["keyword", "vector"], ...]
    keyword_rank: int | None
    vector_rank: int | None


async def hybrid_search(
    query: str,
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
    filters: SearchFilters,
) -> list[SearchResult]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be blank")

    query_vector = await embedding_provider.embed_query(normalized_query)
    candidate_limit = max(filters.limit * 3, 20)
    keyword_candidates = await search_keywords(
        session,
        normalized_query,
        filters,
        candidate_limit=candidate_limit,
    )
    vector_candidates = await search_vectors(
        session,
        query_vector,
        filters,
        candidate_limit=candidate_limit,
    )
    return reciprocal_rank_fusion(
        keyword_candidates,
        vector_candidates,
        limit=filters.limit,
    )


async def search_keywords(
    session: AsyncSession,
    query: str,
    filters: SearchFilters,
    *,
    candidate_limit: int,
) -> list[RetrievalCandidate]:
    normalized_query = query.strip()
    _validate_candidate_limit(candidate_limit)
    if not normalized_query:
        raise ValueError("query must not be blank")

    searchable_text = func.concat(Document.title, literal(" "), Chunk.chunk_text)
    document_vector = func.to_tsvector(literal_column("'simple'"), searchable_text)
    query_vector = func.websearch_to_tsquery(literal_column("'simple'"), normalized_query)
    rank = func.ts_rank_cd(document_vector, query_vector)
    statement = (
        _candidate_statement(filters)
        .where(document_vector.op("@@")(query_vector))
        .order_by(rank.desc(), Chunk.id)
        .limit(candidate_limit)
    )
    return await _load_candidates(session, statement)


async def search_vectors(
    session: AsyncSession,
    query_vector: list[float],
    filters: SearchFilters,
    *,
    candidate_limit: int,
) -> list[RetrievalCandidate]:
    _validate_candidate_limit(candidate_limit)
    if len(query_vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"query vector must contain exactly {EMBEDDING_DIMENSIONS} values")

    distance = Chunk.embedding.cosine_distance(query_vector)
    statement = (
        _candidate_statement(filters).order_by(distance.asc(), Chunk.id).limit(candidate_limit)
    )
    return await _load_candidates(session, statement)


def reciprocal_rank_fusion(
    keyword_candidates: list[RetrievalCandidate],
    vector_candidates: list[RetrievalCandidate],
    *,
    limit: int,
    rank_constant: int = 60,
) -> list[SearchResult]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if rank_constant < 1:
        raise ValueError("rank_constant must be at least 1")

    candidates: dict[uuid.UUID, RetrievalCandidate] = {}
    keyword_ranks = _record_ranks(keyword_candidates, candidates)
    vector_ranks = _record_ranks(vector_candidates, candidates)

    ranked = sorted(
        candidates.values(),
        key=lambda candidate: (
            -_fusion_score(
                keyword_ranks.get(candidate.chunk_id),
                vector_ranks.get(candidate.chunk_id),
                rank_constant,
            ),
            str(candidate.chunk_id),
        ),
    )
    return [
        _to_result(
            candidate,
            keyword_ranks.get(candidate.chunk_id),
            vector_ranks.get(candidate.chunk_id),
            rank_constant,
        )
        for candidate in ranked[:limit]
    ]


def _candidate_statement(
    filters: SearchFilters,
) -> Select[tuple[Chunk, DocumentVersion, Document]]:
    statement = (
        select(Chunk, DocumentVersion, Document)
        .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(
            Document.is_deleted.is_(False),
            DocumentVersion.is_current.is_(True),
        )
    )
    if filters.project is not None:
        statement = statement.where(Document.project == filters.project)
    if filters.domain is not None:
        statement = statement.where(Document.domain == filters.domain)
    if filters.source_type is not None:
        statement = statement.where(Document.source_type == filters.source_type)
    if filters.document_type is not None:
        statement = statement.where(Document.document_type == filters.document_type)
    if filters.tags:
        statement = statement.where(Document.tags.contains(filters.tags))
    if filters.updated_from is not None:
        statement = statement.where(Document.updated_at >= filters.updated_from)
    if filters.updated_to is not None:
        statement = statement.where(Document.updated_at <= filters.updated_to)
    return statement


async def _load_candidates(
    session: AsyncSession,
    statement: Select[tuple[Chunk, DocumentVersion, Document]],
) -> list[RetrievalCandidate]:
    rows = (await session.execute(statement)).all()
    return [
        RetrievalCandidate(
            chunk_id=chunk.id,
            document_id=document.id,
            document_version_id=document_version.id,
            title=document.title,
            source_path=document.source_path,
            heading_path=tuple(chunk.heading_path),
            chunk_text=chunk.chunk_text,
            metadata={
                **document.metadata_,
                "chunk_metadata": chunk.metadata_,
                "source_key": document.source_key,
                "project": document.project,
                "domain": document.domain,
                "source_type": document.source_type,
                "document_type": document.document_type,
                "tags": document.tags,
                "access_scope": document.access_scope,
                "llm_policy": document.llm_policy,
            },
        )
        for chunk, document_version, document in rows
    ]


def _validate_candidate_limit(candidate_limit: int) -> None:
    if candidate_limit < 1:
        raise ValueError("candidate_limit must be at least 1")


def _record_ranks(
    ranked_candidates: list[RetrievalCandidate],
    candidates: dict[uuid.UUID, RetrievalCandidate],
) -> dict[uuid.UUID, int]:
    ranks: dict[uuid.UUID, int] = {}
    for rank, candidate in enumerate(ranked_candidates, start=1):
        candidates.setdefault(candidate.chunk_id, candidate)
        ranks.setdefault(candidate.chunk_id, rank)
    return ranks


def _fusion_score(
    keyword_rank: int | None,
    vector_rank: int | None,
    rank_constant: int,
) -> float:
    return sum(
        1 / (rank_constant + rank) for rank in (keyword_rank, vector_rank) if rank is not None
    )


def _to_result(
    candidate: RetrievalCandidate,
    keyword_rank: int | None,
    vector_rank: int | None,
    rank_constant: int,
) -> SearchResult:
    matched_by: tuple[Literal["keyword", "vector"], ...] = tuple(
        source
        for source, rank in (("keyword", keyword_rank), ("vector", vector_rank))
        if rank is not None
    )
    return SearchResult(
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        document_version_id=candidate.document_version_id,
        title=candidate.title,
        source_path=candidate.source_path,
        heading_path=candidate.heading_path,
        chunk_text=candidate.chunk_text,
        metadata=candidate.metadata,
        score=_fusion_score(keyword_rank, vector_rank, rank_constant),
        matched_by=matched_by,
        keyword_rank=keyword_rank,
        vector_rank=vector_rank,
    )
