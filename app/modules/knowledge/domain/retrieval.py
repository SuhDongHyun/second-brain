from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Represent normalized filters and result limits for knowledge retrieval.
    Construction rejects blank values, naive dates, and invalid ranges."""

    project: str | None = None
    domain: str | None = None
    source_type: str | None = None
    document_type: str | None = None
    tags: list[str] = field(default_factory=list)
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    limit: int = 10

    def __post_init__(self) -> None:
        """Normalize textual filters and enforce cross-field search invariants.
        Frozen fields are updated only to store their canonical stripped values."""
        if not 1 <= self.limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        for name in ("project", "domain", "source_type", "document_type"):
            value = getattr(self, name)
            if value is None:
                continue
            normalized = value.strip()
            if not normalized:
                raise ValueError("filter values must not be blank")
            object.__setattr__(self, name, normalized)

        normalized_tags = [tag.strip() for tag in self.tags]
        if any(not tag for tag in normalized_tags):
            raise ValueError("tags must not contain blank values")
        object.__setattr__(self, "tags", normalized_tags)

        for value in (self.updated_from, self.updated_to):
            if value is not None and value.utcoffset() is None:
                raise ValueError("date filters must be timezone-aware")
        if (
            self.updated_from is not None
            and self.updated_to is not None
            and self.updated_from > self.updated_to
        ):
            raise ValueError("updated_from must not be after updated_to")


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """Carry one storage-independent chunk candidate from a search channel.
    Identity and provenance fields allow later fusion without ORM objects."""

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
    """Represent a fused knowledge result with score and channel provenance.
    Per-channel ranks explain how keyword and vector retrieval contributed."""

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


def reciprocal_rank_fusion(
    keyword_candidates: list[RetrievalCandidate],
    vector_candidates: list[RetrievalCandidate],
    *,
    limit: int,
    rank_constant: int = 60,
) -> list[SearchResult]:
    """Merge keyword and vector rankings into deterministic search results.
    Each channel contributes a reciprocal-rank score before limiting the output."""
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


def _record_ranks(
    ranked_candidates: list[RetrievalCandidate],
    candidates: dict[uuid.UUID, RetrievalCandidate],
) -> dict[uuid.UUID, int]:
    """Record the first rank of each candidate while building a shared index.
    Duplicate chunks retain their earliest position within a retrieval channel."""
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
    """Calculate the reciprocal-rank contribution from available channels.
    Missing channel ranks contribute nothing to the combined score."""
    return sum(
        1 / (rank_constant + rank) for rank in (keyword_rank, vector_rank) if rank is not None
    )


def _to_result(
    candidate: RetrievalCandidate,
    keyword_rank: int | None,
    vector_rank: int | None,
    rank_constant: int,
) -> SearchResult:
    """Convert a candidate and its channel ranks into a fused result.
    The conversion records match sources and computes the final score once."""
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
