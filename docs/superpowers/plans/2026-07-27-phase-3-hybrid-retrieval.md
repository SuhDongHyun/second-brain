# Phase 3 Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 버전의 Markdown Chunk를 keyword와 vector로 검색하고 metadata filter, rank fusion, 추적 가능한 source를 반환하는 Hybrid Retrieval API를 만든다.

**Architecture:** PostgreSQL이 Korean/English full-text search와 pgvector cosine search를 각각 수행하고, Python service가 두 순위 목록을 Reciprocal Rank Fusion(RRF)으로 결합한다. 검색은 `Document.is_deleted=false`와 `DocumentVersion.is_current=true`만 대상으로 하며, API는 답변 생성 없이 검색 Chunk와 원본 추적 정보만 반환한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x Async, PostgreSQL 16 full-text search, pgvector, pytest/pytest-asyncio, Ruff

## Global Constraints

- Phase 3 범위는 keyword search, vector search, metadata filter, result fusion, source 반환이다.
- OpenDART, Google ADK, Knowledge Workspace, provenance graph 저장, Oracle Sync는 추가하지 않는다.
- 문서 embedding과 질문 embedding은 같은 provider/model/dimensions를 사용한다.
- 삭제 문서와 과거 DocumentVersion은 검색 결과에서 제외한다.
- `local_only` 문서는 검색할 수 있지만 외부 LLM으로 보내는 정책은 Phase 5에서 처리한다.
- 점수 결합은 원시 keyword/vector 점수의 척도를 섞지 않고 RRF를 사용한다.
- 각 Task는 테스트를 먼저 실패시킨 뒤 최소 구현으로 통과시킨다.

---

### Task 1: 검색 계약과 Reciprocal Rank Fusion

**Files:**
- Create: `app/retrieval.py`
- Create: `tests/unit/test_retrieval_fusion.py`

**Interfaces:**
- Produces: `SearchFilters`, `RetrievalCandidate`, `SearchResult`
- Produces: `reciprocal_rank_fusion(keyword_candidates, vector_candidates, *, limit, rank_constant=60) -> list[SearchResult]`

- [x] `SearchFilters`가 project/domain/source/document type, tags, updated range, 1–50 limit를 검증하는 실패 테스트를 작성한다.
- [x] 두 후보 목록의 중복 Chunk가 하나로 합쳐지고 양쪽 rank가 보존되는 실패 테스트를 작성한다.
- [x] RRF 점수 `Σ 1 / (60 + rank)`와 동일 점수 UUID tie-break를 검증한다.
- [x] frozen retrieval data contract와 최소 fusion 함수를 구현한다.
- [x] `uv run pytest tests/unit/test_retrieval_fusion.py -v`와 Ruff를 실행한다.

### Task 2: PostgreSQL Keyword 및 Vector Retriever

**Files:**
- Modify: `app/retrieval.py`
- Create: `tests/integration/test_retrieval.py`

**Interfaces:**
- Consumes: `AsyncSession`, 1024차원 query vector, `SearchFilters`
- Produces: `search_keywords(session, query, filters, candidate_limit) -> list[RetrievalCandidate]`
- Produces: `search_vectors(session, query_vector, filters, candidate_limit) -> list[RetrievalCandidate]`

- [x] current version과 non-deleted 문서만 반환하는 integration test fixture를 작성한다.
- [x] `websearch_to_tsquery('simple', :query)`와 `ts_rank_cd`가 Korean/English 키워드를 찾는 실패 테스트를 작성한다.
- [x] pgvector cosine distance가 가장 가까운 Chunk를 먼저 반환하는 실패 테스트를 작성한다.
- [x] project/domain/source/document type exact match, tags containment, updated range 조합 테스트를 작성한다.
- [x] 공통 SQLAlchemy predicate와 row-to-candidate 변환을 구현하고 각 검색을 `candidate_limit`으로 제한한다.
- [x] 빈/공백 query와 1024가 아닌 vector를 DB 호출 전에 거부한다.
- [x] `uv run pytest tests/integration/test_retrieval.py -v`를 실행한다.

### Task 3: Hybrid Retrieval Service

**Files:**
- Modify: `app/retrieval.py`
- Create: `tests/unit/test_hybrid_search.py`

**Interfaces:**
- Consumes: `EmbeddingProvider.embed_query`, Task 2 retriever, `SearchFilters`
- Produces: `hybrid_search(query, session, embedding_provider, filters) -> list[SearchResult]`

- [x] query embedding이 한 번만 생성되고 keyword/vector 검색이 각각 호출되는 실패 테스트를 작성한다.
- [x] 각 채널에서 `max(limit * 3, 20)` 후보를 받아 RRF 후 limit를 적용하는 테스트를 작성한다.
- [x] 한 채널이 빈 결과여도 다른 채널 결과를 반환하고 provider/retrieval 오류는 숨기지 않는 테스트를 작성한다.
- [x] 입력 query를 trim하고 빈 문자열을 거부하는 최소 orchestration을 구현한다.
- [x] `uv run pytest tests/unit/test_hybrid_search.py -v`를 실행한다.

### Task 4: Query API와 Source 응답

**Files:**
- Create: `app/api/query.py`
- Modify: `app/main.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Create: `tests/integration/test_query_api.py`

**Interfaces:**
- Consumes: `POST /api/v1/query` body `{query, filters}`
- Produces: `{query, results: [{chunk_id, score, matched_by, text, source}]}`

- [x] provider와 DB dependency를 override한 API success/validation/error 테스트를 작성한다.
- [x] source에 document/document-version/chunk ID, title, source path, heading path, metadata를 포함한다.
- [x] API lifespan에서 재사용 가능한 Ollama provider를 만들고 종료 시 client를 닫는다.
- [x] 검색 결과가 없으면 HTTP 200과 빈 `results`를 반환하고 provider 장애는 HTTP 503으로 매핑한다.
- [x] `uv run pytest tests/integration/test_query_api.py -v`를 실행한다.

### Task 5: 대표 질문 End-to-End 검증과 문서화

**Files:**
- Create: `knowledge/samples/11-oracle-adk-troubleshooting.md`
- Create: `knowledge/samples/12-trading-api-role.md`
- Modify: `README.md`
- Modify: `docs/PLAN.md`
- Modify only if verification finds an issue: Task 1–4 files

**Interfaces:**
- Consumes: Phase 2 ingestion CLI와 Phase 3 Query API
- Produces: Blueprint의 두 대표 질문에 대한 재현 가능한 검색 결과

- [x] 자격 증명 없이 ADK 접속 해결 기록과 trading-api 역할을 설명하는 유효한 sample Markdown을 작성한다.
- [x] ingest 후 두 질문 모두 기대 문서를 상위 결과로 반환하는 integration test를 작성한다.
- [x] README에 migration/ingest/server/query 예제와 filter 필드를 기록한다.
- [x] `uv lock --check`, 전체 pytest, Ruff lint/format, `git diff --check`를 실행한다.
- [x] 실제 PostgreSQL/pgvector와 Ollama 환경에서 두 대표 질문을 호출하고 source chain을 확인한다.
- [x] `docs/PLAN.md` 진행 상태와 테스트 수를 실제 결과로 갱신한다.

## Completion Evidence

```bash
uv lock --check
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
git diff --check
```

다음 두 질문의 검색 결과 첫 페이지에 각각 관련 source가 포함되어야 한다.

```text
Oracle Cloud에서 ADK 접속 문제를 어떻게 해결했지?
trading-api는 어떤 역할을 하는 프로젝트야?
```
