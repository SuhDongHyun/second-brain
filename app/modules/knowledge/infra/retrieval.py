from sqlalchemy import Select, func, literal, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.domain.retrieval import RetrievalCandidate, SearchFilters
from app.modules.knowledge.infra.models import Chunk, Document, DocumentVersion

EMBEDDING_DIMENSIONS = 1024


async def search_keywords(
    session: AsyncSession,
    query: str,
    filters: SearchFilters,
    *,
    candidate_limit: int,
) -> list[RetrievalCandidate]:
    """Retrieve ranked chunks with PostgreSQL full-text search.
    The query combines document titles and chunk text before applying filters."""
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
    """Retrieve chunks ordered by pgvector cosine distance.
    Vector dimensions and candidate limits are validated before SQL execution."""
    _validate_candidate_limit(candidate_limit)
    if len(query_vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"query vector must contain exactly {EMBEDDING_DIMENSIONS} values")

    distance = Chunk.embedding.cosine_distance(query_vector)
    statement = (
        _candidate_statement(filters).order_by(distance.asc(), Chunk.id).limit(candidate_limit)
    )
    return await _load_candidates(session, statement)


def _candidate_statement(
    filters: SearchFilters,
) -> Select[tuple[Chunk, DocumentVersion, Document]]:
    """Build the shared current-document candidate query with domain filters.
    Keyword and vector searches add only their ranking-specific clauses."""
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
    """Execute a candidate statement and detach rows from ORM representation.
    Document and chunk metadata are combined into retrieval provenance."""
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
                "updated_at": document.updated_at.isoformat(),
                "valid_from": (
                    document.valid_from.isoformat() if document.valid_from is not None else None
                ),
                "valid_to": (
                    document.valid_to.isoformat() if document.valid_to is not None else None
                ),
            },
        )
        for chunk, document_version, document in rows
    ]


def _validate_candidate_limit(candidate_limit: int) -> None:
    """Require at least one candidate from each retrieval channel.
    Invalid limits fail before constructing or executing a database query."""
    if candidate_limit < 1:
        raise ValueError("candidate_limit must be at least 1")
