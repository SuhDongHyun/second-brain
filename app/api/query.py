from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.embeddings import EmbeddingError, EmbeddingProvider
from app.retrieval import SearchFilters, SearchResult, hybrid_search

router = APIRouter(prefix="/api/v1", tags=["query"])


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized


class SourceResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    title: str
    source_path: str
    heading_path: tuple[str, ...]
    metadata: dict[str, Any]


class QueryResultResponse(BaseModel):
    score: float
    matched_by: tuple[Literal["keyword", "vector"], ...]
    keyword_rank: int | None
    vector_rank: int | None
    text: str
    source: SourceResponse


class QueryResponse(BaseModel):
    query: str
    results: list[QueryResultResponse]


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider


async def execute_query(
    payload: QueryRequest,
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
) -> list[SearchResult]:
    return await hybrid_search(
        payload.query,
        session,
        embedding_provider,
        payload.filters,
    )


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> QueryResponse:
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
