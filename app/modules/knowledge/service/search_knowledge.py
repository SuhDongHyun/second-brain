from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.domain.retrieval import (
    SearchFilters,
    SearchResult,
    reciprocal_rank_fusion,
)
from app.modules.knowledge.infra.embedding import EmbeddingProvider
from app.modules.knowledge.infra.retrieval import search_keywords, search_vectors


async def hybrid_search(
    query: str,
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
    filters: SearchFilters,
) -> list[SearchResult]:
    """Coordinate embedding, keyword retrieval, vector retrieval, and fusion.
    Each channel fetches extra candidates before the domain applies the final limit."""
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
