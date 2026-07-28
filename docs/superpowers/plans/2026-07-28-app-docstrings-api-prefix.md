# App Docstrings and API Prefix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document every class and callable under `app/` with concise English docstrings and expose the query endpoint at `POST /api/query`.

**Architecture:** Add documentation without changing application boundaries or callable signatures. Change only the knowledge router prefix and its active README and integration-test consumers; retain historical design records unchanged.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, pytest, Ruff

## Global Constraints

- Every class, function, method, property, validator, protocol method, private helper, and nested function under `app/` receives a non-empty English docstring.
- Each docstring uses two or three concise source lines describing purpose, role, and essential logic.
- The query endpoint changes from `POST /api/v1/query` to `POST /api/query` without a compatibility alias.
- Existing behavior, signatures, and the user's unrelated working-tree changes remain intact.

---

### Task 1: Document Root and Configuration Modules

**Files:**
- Modify: `app/composition.py`
- Modify: `app/config.py`
- Modify: `app/db.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: Existing settings, database session, embedding provider, and FastAPI lifecycle interfaces.
- Produces: The same runtime interfaces with English introspection documentation.

- [ ] **Step 1: Add two- or three-line docstrings**

Add docstrings immediately below every class and callable declaration. For example:

```python
def create_embedding_provider(settings: Settings) -> OllamaEmbeddingProvider:
    """Build the application's embedding adapter from validated settings.

    The provider is returned unopened so the FastAPI lifespan owns its cleanup.
    """
```

- [ ] **Step 2: Run focused lint**

Run: `uv run ruff check app/composition.py app/config.py app/db.py app/main.py`

Expected: exit code 0.

### Task 2: Document Financial Modules

**Files:**
- Modify: `app/modules/financial/domain/financial.py`
- Modify: `app/modules/financial/infra/files.py`
- Modify: `app/modules/financial/infra/opendart.py`
- Modify: `app/modules/financial/service/collect_company_financials.py`
- Modify: `app/modules/financial/service/render_financial_markdown.py`

**Interfaces:**
- Consumes: Existing financial domain contracts, OpenDART responses, and file paths.
- Produces: Unchanged financial collection and rendering behavior with documented responsibilities.

- [ ] **Step 1: Add two- or three-line docstrings**

Document domain values, exceptions, client lifecycle methods, conversion helpers, file writers,
collection orchestration, and Markdown rendering. Preserve decorators and signatures:

```python
def parse_amount(value: str | None) -> Decimal | None:
    """Convert an OpenDART amount string into a normalized decimal value.

    Blank values become ``None`` while commas are removed before conversion.
    """
```

- [ ] **Step 2: Run focused tests and lint**

Run: `uv run pytest tests/unit/test_financial_domain.py tests/unit/test_financial_files.py tests/unit/test_financial_markdown.py tests/unit/test_opendart.py tests/unit/test_collect_company_financials.py -q`

Expected: all selected tests pass.

Run: `uv run ruff check app/modules/financial`

Expected: exit code 0.

### Task 3: Document Knowledge Modules

**Files:**
- Modify: `app/modules/knowledge/domain/document.py`
- Modify: `app/modules/knowledge/domain/retrieval.py`
- Modify: `app/modules/knowledge/infra/embedding.py`
- Modify: `app/modules/knowledge/infra/models.py`
- Modify: `app/modules/knowledge/infra/retrieval.py`
- Modify: `app/modules/knowledge/interface/controller.py`
- Modify: `app/modules/knowledge/interface/schema.py`
- Modify: `app/modules/knowledge/service/chunk_markdown.py`
- Modify: `app/modules/knowledge/service/ingest_markdown.py`
- Modify: `app/modules/knowledge/service/search_knowledge.py`
- Modify: `app/modules/health/interface/controller.py`
- Modify: `app/modules/health/interface/schema.py`

**Interfaces:**
- Consumes: Existing document parsing, retrieval, ingestion, query, and health interfaces.
- Produces: Identical interfaces with documented validation, transformation, and orchestration logic.

- [ ] **Step 1: Add two- or three-line docstrings**

Document all models, errors, protocol members, lifecycle methods, private helpers, validators,
route handlers, and the nested chunk-section `flush` helper. Preserve executable bodies:

```python
def reciprocal_rank_fusion(
    keyword_candidates: list[RetrievalCandidate],
    vector_candidates: list[RetrievalCandidate],
    *,
    limit: int,
    rank_constant: int = 60,
) -> list[SearchResult]:
    """Merge keyword and vector rankings into deterministic search results.

    Each channel contributes a reciprocal-rank score before results are sorted and limited.
    """
```

- [ ] **Step 2: Audit docstring coverage with the AST**

Run a Python AST scan over `app/**/*.py` that reports any `ClassDef`, `FunctionDef`, or
`AsyncFunctionDef` where `ast.get_docstring(node)` is false.

Expected: no paths or symbol names are printed.

- [ ] **Step 3: Run focused tests and lint**

Run: `uv run pytest tests/unit tests/integration/test_health.py tests/integration/test_query_api.py -q`

Expected: all selected tests pass.

Run: `uv run ruff check app`

Expected: exit code 0.

### Task 4: Change the Query API Prefix

**Files:**
- Modify: `app/modules/knowledge/interface/controller.py`
- Modify: `tests/integration/test_query_api.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Existing `POST /api/v1/query` request and response contract.
- Produces: The same contract at `POST /api/query`.

- [ ] **Step 1: Change the router prefix**

```python
router = APIRouter(prefix="/api", tags=["query"])
```

- [ ] **Step 2: Update active consumers**

Replace `/api/v1/query` with `/api/query` in `tests/integration/test_query_api.py` and
the endpoint description and curl example in `README.md`. Do not edit historical documents.

- [ ] **Step 3: Run endpoint verification**

Run: `uv run pytest tests/integration/test_query_api.py -q`

Expected: all query API tests pass at `/api/query`.

Run: `rg -n '/api/v1/query' app README.md tests`

Expected: no matches.

### Task 5: Final Verification

**Files:**
- Verify: `app/**/*.py`
- Verify: `tests/integration/test_query_api.py`
- Verify: `README.md`

**Interfaces:**
- Consumes: Completed documentation and route changes.
- Produces: Evidence that formatting, tests, docstring coverage, and the active API contract are correct.

- [ ] **Step 1: Check the diff**

Run: `git diff --check`

Expected: exit code 0.

- [ ] **Step 2: Run complete static and unit verification**

Run: `uv run ruff check app tests`

Expected: exit code 0.

Run: `uv run pytest tests/unit -q`

Expected: all unit tests pass.

- [ ] **Step 3: Review scope**

Run: `git diff --stat`

Expected: only the requested documentation, query route, active README, and test updates are attributable to this implementation; pre-existing user changes remain preserved.
