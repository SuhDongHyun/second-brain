import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.retrieval import RetrievalCandidate, SearchFilters, reciprocal_rank_fusion


def candidate(label: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"chunk:{label}"),
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, f"document:{label}"),
        document_version_id=uuid.uuid5(uuid.NAMESPACE_URL, f"version:{label}"),
        title=f"Title {label}",
        source_path=f"knowledge/{label}.md",
        heading_path=("Overview",),
        chunk_text=f"Body {label}",
        metadata={"label": label},
    )


def test_search_filters_reject_invalid_limit_and_blank_values() -> None:
    with pytest.raises(ValidationError):
        SearchFilters(limit=0)
    with pytest.raises(ValidationError):
        SearchFilters(project=" ")
    with pytest.raises(ValidationError):
        SearchFilters(tags=["valid", " "])


def test_search_filters_require_timezone_aware_ordered_date_range() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        SearchFilters(updated_from=datetime(2026, 7, 1))
    with pytest.raises(ValidationError, match="updated_from must not be after updated_to"):
        SearchFilters(
            updated_from=datetime(2026, 7, 2, tzinfo=UTC),
            updated_to=datetime(2026, 7, 1, tzinfo=UTC),
        )


def test_reciprocal_rank_fusion_combines_and_deduplicates_candidates() -> None:
    shared = candidate("shared")
    keyword_only = candidate("keyword")
    vector_only = candidate("vector")

    results = reciprocal_rank_fusion(
        keyword_candidates=[shared, keyword_only],
        vector_candidates=[vector_only, shared],
        limit=3,
        rank_constant=60,
    )

    assert [result.chunk_id for result in results] == [
        shared.chunk_id,
        vector_only.chunk_id,
        keyword_only.chunk_id,
    ]
    assert results[0].matched_by == ("keyword", "vector")
    assert results[0].keyword_rank == 1
    assert results[0].vector_rank == 2
    assert results[1].matched_by == ("vector",)
    assert results[2].matched_by == ("keyword",)
    assert results[0].score == pytest.approx((1 / 61) + (1 / 62))


def test_reciprocal_rank_fusion_is_deterministic_for_equal_scores() -> None:
    first = candidate("first")
    second = candidate("second")

    results = reciprocal_rank_fusion(
        keyword_candidates=[first],
        vector_candidates=[second],
        limit=1,
        rank_constant=60,
    )

    expected = min(first.chunk_id, second.chunk_id, key=str)
    assert results[0].chunk_id == expected


def test_reciprocal_rank_fusion_validates_arguments() -> None:
    with pytest.raises(ValueError, match="limit"):
        reciprocal_rank_fusion([], [], limit=0)
    with pytest.raises(ValueError, match="rank_constant"):
        reciprocal_rank_fusion([], [], limit=1, rank_constant=0)
