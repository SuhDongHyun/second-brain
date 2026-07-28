from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.modules.knowledge.domain.retrieval import SearchResult
from app.modules.knowledge.infra.embedding import EmbeddingError, EmbeddingProvider
from app.modules.knowledge.interface.schema import (
    QueryRequest,
    QueryResponse,
    QueryResultResponse,
    SourceResponse,
)
from app.modules.knowledge.service.search_knowledge import hybrid_search

router = APIRouter(prefix="/api", tags=["query"])


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    """Resolve the application-scoped embedding provider for FastAPI.
    The lifespan stores the initialized adapter on application state."""
    return request.app.state.embedding_provider


async def execute_query(
    payload: QueryRequest,
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
) -> list[SearchResult]:
    """Translate an HTTP query model into the knowledge search use case.
    Validated interface filters are explicitly mapped to their domain value."""
    return await hybrid_search(
        payload.query,
        session,
        embedding_provider,
        payload.filters.to_domain(),
    )


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> QueryResponse:
    """Execute a knowledge query and serialize its ranked evidence.
    Embedding and database failures are exposed as a stable 503 response."""
    try:
        results = await execute_query(payload, session, embedding_provider)
        response_results = [_serialize_result(result) for result in results]
    except (EmbeddingError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="retrieval service unavailable",
        ) from exc
    return QueryResponse(query=payload.query.strip(), results=response_results)


def _serialize_result(result: SearchResult) -> QueryResultResponse:
    """Map one domain search result into the public response schema.
    Retrieval provenance is nested under the response's source object."""
    return QueryResultResponse(
        score=result.score,
        matched_by=result.matched_by,
        keyword_rank=result.keyword_rank,
        vector_rank=result.vector_rank,
        text=result.chunk_text,
        source=SourceResponse(
            document_id=result.document_id,
            document_version_id=result.document_version_id,
            chunk_id=result.chunk_id,
            title=result.title,
            source_path=result.source_path,
            heading_path=result.heading_path,
            metadata=result.metadata,
        ),
    )
