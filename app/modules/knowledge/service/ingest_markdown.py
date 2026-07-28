from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.domain.document import ParsedMarkdown, parse_markdown
from app.modules.knowledge.infra.embedding import EmbeddingError, EmbeddingProvider
from app.modules.knowledge.infra.models import Chunk, Document, DocumentVersion
from app.modules.knowledge.service.chunk_markdown import chunk_markdown, embedding_text


class IngestionResult(StrEnum):
    """Enumerate observable outcomes of a Markdown ingestion attempt.
    Values are stable strings for CLI output and collection summaries."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def _document_values(parsed: ParsedMarkdown) -> dict[str, object]:
    """Map parsed metadata into writable document persistence fields.
    The computed content hash is included in the stored metadata snapshot."""
    metadata = parsed.metadata
    stored_metadata = metadata.model_dump(mode="json")
    stored_metadata["content_hash"] = parsed.content_hash
    return {
        "source_path": str(parsed.source_path),
        "title": metadata.title,
        "source_type": metadata.source_type,
        "document_type": metadata.document_type,
        "domain": metadata.domain,
        "project": metadata.project,
        "language": metadata.language,
        "access_scope": metadata.access_scope,
        "llm_policy": metadata.llm_policy,
        "created_at": metadata.created_at,
        "updated_at": metadata.updated_at,
        "observed_at": metadata.observed_at,
        "valid_from": metadata.valid_from,
        "valid_to": metadata.valid_to,
        "tags": metadata.tags,
        "metadata_": stored_metadata,
        "is_deleted": False,
    }


async def ingest_markdown(
    path: Path,
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
) -> IngestionResult:
    """Ingest a Markdown file as a versioned, embedded knowledge document.
    One transaction coordinates deduplication, chunking, vectors, and current version state."""
    parsed = parse_markdown(path)
    if parsed.metadata.llm_policy == "local_only" and not embedding_provider.is_local:
        raise EmbeddingError("local-only document requires a local embedding provider")

    async with session.begin():
        document = await session.scalar(
            select(Document).where(Document.source_key == parsed.metadata.id)
        )
        current: DocumentVersion | None = None
        if document is not None:
            current = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.is_current.is_(True),
                )
            )
            if current is not None and current.content_hash == parsed.content_hash:
                document.source_path = str(parsed.source_path)
                return IngestionResult.UNCHANGED

        chunks = chunk_markdown(parsed)
        if not chunks:
            raise ValueError("Markdown produced no chunks")
        vectors = await embedding_provider.embed_documents(
            [embedding_text(parsed, chunk) for chunk in chunks]
        )
        if len(vectors) != len(chunks):
            raise EmbeddingError("embedding count does not match chunk count")
        if any(len(vector) != embedding_provider.dimensions for vector in vectors):
            raise EmbeddingError("embedding dimensions do not match provider dimensions")

        result = IngestionResult.CREATED
        if document is None:
            document = Document(source_key=parsed.metadata.id, **_document_values(parsed))
            session.add(document)
            await session.flush()
            next_version = 1
        else:
            result = IngestionResult.UPDATED
            for key, value in _document_values(parsed).items():
                setattr(document, key, value)
            next_version = (
                int(
                    await session.scalar(
                        select(func.coalesce(func.max(DocumentVersion.version), 0)).where(
                            DocumentVersion.document_id == document.id
                        )
                    )
                    or 0
                )
                + 1
            )
            if current is not None:
                current.is_current = False
                await session.flush()

        version = DocumentVersion(
            document_id=document.id,
            version=next_version,
            content_path=str(parsed.source_path),
            normalized_content=parsed.normalized_content,
            content_hash=parsed.content_hash,
            is_current=True,
        )
        session.add(version)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_version_id=version.id,
                    chunk_index=chunk.chunk_index,
                    heading_path=list(chunk.heading_path),
                    chunk_type=chunk.chunk_type,
                    chunk_text=chunk.chunk_text,
                    token_count=chunk.token_count,
                    content_hash=chunk.content_hash,
                    metadata_={},
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
        )
        return result
