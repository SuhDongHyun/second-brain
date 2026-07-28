# Personal Second-Brain

Phase 1–5 builds the local Markdown knowledge pipeline, Hybrid Retrieval, OpenDART
collection, and Google ADK answer API described in [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md).

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

The knowledge query Tool embeds each question with the configured Ollama model,
searches current non-deleted chunks with PostgreSQL full-text search and pgvector
cosine distance, and combines both rankings with Reciprocal Rank Fusion. Google ADK
uses the resulting evidence internally when serving `POST /api/query`.

Supported filters are `project`, `domain`, `source_type`, `document_type`, `tags`,
`updated_from`, `updated_to`, and `limit`. Scalar metadata uses exact matching,
`tags` requires all supplied tags, dates are timezone-aware ISO 8601 values, and
the answer API `limit` must be between 1 and 8.

## OpenDART financial reports

Set `OPENDART__API_KEY` in `.env`, then collect all available annual, semiannual,
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

## Google ADK answers

Set a Google AI Studio API key in `.env` before using the answer endpoint:

```env
ADK__API_KEY=your-api-key
ADK__MODEL=gemma-4-31b-it
```

`POST /api/query` asks a hosted Gemma model to call one of two Google ADK Function
Tools before answering:

- `search_knowledge` uses the existing Hybrid Retrieval for general knowledge.
- `query_financial_facts` restricts the same Hybrid Retrieval to
  `domain=finance` and `source_type=opendart`.

The financial Tool searches generated OpenDART Markdown. It is not a SQL aggregation
or a financial facts table, and it does not calculate ratios or investment advice.

```bash
curl --fail-with-body http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "삼성전자의 가장 최근 연결재무제표를 요약해줘.",
    "filters": {
      "domain": "finance",
      "limit": 6
    }
  }'
```

The response contains `answer`, `conversation_id`, source provenance,
retrieval diagnostics, and model information. The returned `conversation_id` is a
request-correlation identifier. Each turn uses an isolated ephemeral ADK session and
excludes previous messages and Tool payloads from model context, so questions must be
self-contained and a later request cannot bypass its current filters.

If any retrieved document is marked `llm_policy: local_only`, the Tool sends no
document content or metadata to Google. The API returns a fixed policy-limited answer
and an empty source list. An empty `ADK__API_KEY` does not prevent application startup
or `/health`; `POST /api/query` returns HTTP 503 until the key is configured.

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

## Current scope

The current implementation supports Markdown ingestion, Hybrid Retrieval, OpenDART
financial Markdown, and grounded Google ADK answer generation. URL, PDF, PPT/PPTX
intake, Graphify, Oracle synchronization, persistent conversation storage, and the
Knowledge Workspace UI remain deferred as documented in [`docs/PLAN.md`](docs/PLAN.md).
