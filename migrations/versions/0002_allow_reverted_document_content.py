"""Allow document versions to revert to earlier content.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "document_versions_document_id_content_hash_key",
        "document_versions",
        type_="unique",
    )


def downgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT document_id, content_hash
            FROM document_versions
            GROUP BY document_id, content_hash
            HAVING count(*) > 1
            LIMIT 1
            """
            )
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade 0002 while reverted document content exists; "
            "remove duplicate document/content hash versions only if history loss is acceptable"
        )
    op.create_unique_constraint(
        "document_versions_document_id_content_hash_key",
        "document_versions",
        ["document_id", "content_hash"],
    )
