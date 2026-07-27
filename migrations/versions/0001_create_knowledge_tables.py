"""Create knowledge tables.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_key", sa.String(255), nullable=False, unique=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(100), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("domain", sa.String(100), nullable=False),
        sa.Column("project", sa.String(255)),
        sa.Column("language", sa.String(20)),
        sa.Column("access_scope", sa.String(50), nullable=False),
        sa.Column("llm_policy", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_path", sa.Text(), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("document_id", "version"),
        sa.UniqueConstraint("document_id", "content_hash"),
    )
    op.create_index(
        "uq_document_versions_current",
        "document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading_path", postgresql.JSONB(), nullable=False),
        sa.Column("chunk_type", sa.String(50), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("document_version_id", "chunk_index"),
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_index("uq_document_versions_current", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_table("documents")
