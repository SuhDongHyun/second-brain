# Personal Second-Brain

Phase 1–2 builds the local Markdown knowledge pipeline described in
[`docs/BLUEPRINT.md`](docs/BLUEPRINT.md).

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker with Docker Compose
- Ollama with the configured embedding model (default: `bge-m3`)

Copy `.env.example` to `.env` before running local services.

## Development

```bash
uv sync --dev
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`GET /health` checks the API, PostgreSQL connection, and pgvector extension. It returns
HTTP 503 when a required component is unavailable.

Stop the database with `docker compose down`. Removing the volume with
`docker compose down --volumes` permanently deletes the local database.

## Ingest sample knowledge

Pull the embedding model before the first ingest:

```bash
ollama pull bge-m3
uv run python -m scripts.ingest knowledge/samples
```

The first run reports `created=10`. Running the same command again reports
`unchanged=10` and does not call Ollama for unchanged documents. Changing content or
validated metadata creates a new `DocumentVersion`; earlier versions remain stored.
Reverting to earlier content also creates a new version so the full change history is
preserved.

Documents marked `llm_policy: local_only` are embedded only through the built-in
provider configured with a loopback Ollama endpoint. That endpoint must be a directly
controlled local Ollama process; do not place a remote relay or tunnel behind it.

`content_hash` is SHA-256 over canonical JSON metadata (excluding an input
`content_hash`) and the normalized body. Normalization only removes a UTF-8 BOM,
normalizes line endings, removes trailing whitespace, and ensures one final newline.

`Chunk.token_count` is a deterministic regex-based estimate, not a model tokenizer
count. Heading paths and source paths are stored so a later provenance graph can trace
answers back to their source.

## Verification

```bash
uv lock --check
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```

PostgreSQL integration tests use separate disposable databases for ingestion and
destructive migration checks:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://second_brain:second_brain@localhost:5432/second_brain_test \
MIGRATION_TEST_DATABASE_URL=postgresql+asyncpg://second_brain:second_brain@localhost:5432/second_brain_migration_test \
  uv run pytest tests/integration -v
```

Create and dedicate both databases to tests before running this command. The test
suite accepts only loopback database URLs whose names end with `_test`, rejects the
effective application database and matching test URLs, prepares each schema from
Alembic `base`, and returns both schemas to `base` during teardown.

## Phase 1–2 scope

This phase supports Markdown only. URL, PDF, PPT/PPTX intake, hybrid retrieval,
Google ADK, Graphify, Oracle synchronization, and the Knowledge Workspace UI are
intentionally deferred as documented in [`docs/PLAN.md`](docs/PLAN.md).
