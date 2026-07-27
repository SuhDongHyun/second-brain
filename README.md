# Personal Second-Brain

Phase 1–3 builds the local Markdown knowledge pipeline and hybrid retrieval API described in
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

For VS Code debugging, select `Debug Second-Brain API` from Run and Debug. The
configuration launches `uvicorn` from the repository root so the `app` package is
importable. Do not use `Python Debugger: Current File` on `app/main.py`; running that
file directly changes Python's import root to the `app/` directory.

Stop the database with `docker compose down`. Removing the volume with
`docker compose down --volumes` permanently deletes the local database.

## Ingest sample knowledge

Pull the embedding model before the first ingest:

```bash
ollama pull bge-m3
uv run python -m scripts.ingest knowledge/samples
```

The first run reports `created=12`. Running the same command again reports
`unchanged=12` and does not call Ollama for unchanged documents. Changing content or
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

## Hybrid retrieval

`POST /api/v1/query` embeds the question with the configured Ollama model, searches
current non-deleted chunks with PostgreSQL full-text search and pgvector cosine
distance, and combines both rankings with Reciprocal Rank Fusion. It returns search
evidence and source identifiers; it does not generate an LLM answer.

```bash
curl --fail-with-body http://127.0.0.1:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "Oracle Cloud에서 ADK 접속 문제를 어떻게 해결했지?",
    "filters": {
      "project": "second-brain",
      "tags": ["google-adk"],
      "limit": 5
    }
  }'
```

Supported filters are `project`, `domain`, `source_type`, `document_type`, `tags`,
`updated_from`, `updated_to`, and `limit`. Scalar metadata uses exact matching,
`tags` requires all supplied tags, dates are timezone-aware ISO 8601 values, and
`limit` must be between 1 and 50.

Each result contains the Chunk text, RRF score, contributing retrieval channels and
their ranks. The `source` object contains Document, DocumentVersion and Chunk IDs,
title, source path, heading path, and metadata.

## OpenDART financial reports

Set `OPENDART_API_KEY` in `.env`, then collect all available annual, semiannual,
first-quarter, and third-quarter statements for one company and business year:

```bash
uv run python -m scripts.collect_company_info --code 005930 --year 2025
```

Omit `--year` to use the current business year. Add `--dry-run` to call and validate
OpenDART without writing files, connecting to PostgreSQL, or calling Ollama.

Raw responses are written below `raw/opendart/<stock-code>/<year>/`; generated
Markdown is written below `knowledge/generated/opendart/<stock-code>/<year>/`.
Both are local generated data and are ignored by Git. Re-running the command uses
stable paths and the existing ingestion content hash, so unchanged documents do not
create another version or embedding.

Phase 4 does not add financial-specific PostgreSQL tables. The generated Markdown
uses the existing Document, DocumentVersion, and Chunk pipeline. It preserves the
report name, filing date, CFS/OFS distinction, financial values, and receipt number.

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

## Phase 1–3 scope

These phases support Markdown ingestion and evidence retrieval only. URL, PDF,
PPT/PPTX intake, answer generation with Google ADK, Graphify, Oracle synchronization,
and the Knowledge Workspace UI are intentionally deferred as documented in
[`docs/PLAN.md`](docs/PLAN.md).
