# Phase 1–2 Markdown Knowledge Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Python 3.12, FastAPI, PostgreSQL/pgvector를 기반으로 YAML front matter가 있는 Markdown을 결정적으로 파싱·청킹·임베딩하고, 내용 변경분만 버전으로 보존하여 저장하는 최소 기반을 만든다.

**Architecture:** Phase 1–2에서는 로컬 개발 환경의 PostgreSQL에 직접 적재하는 하나의 비동기 파이프라인을 사용한다. API, DB 모델, Markdown 처리, Ollama 어댑터만 얇게 분리하고, 배포 패키지와 Oracle Sync는 후속 Phase에서 현재 저장 인터페이스를 호출하는 방식으로 추가한다.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic v2/pydantic-settings, SQLAlchemy 2.x Async, asyncpg, Alembic, PostgreSQL, pgvector, HTTPX, PyYAML, pytest/pytest-asyncio, Ruff, Docker Compose

## 0. 구현 진행 상태

**최종 갱신:** 2026-07-27

Phase 1–2 구현과 실제 환경 검증을 완료했다. Phase 3 Hybrid Retrieval도
`phase-3-hybrid-retrieval` 브랜치에서 구현과 실제 환경 검증을 완료했다.

완료된 결과:

- FastAPI `/health`가 PostgreSQL 연결과 pgvector extension을 실제 검사한다.
- Alembic `0001`이 Document, DocumentVersion, Chunk schema를 생성한다.
- Alembic `0002`가 A→B→A document content reversion을 새 version으로 보존한다.
- YAML front matter parsing, Markdown normalization, content hash, heading chunking을 구현했다.
- Ollama `bge-m3`가 실제 1024차원 embedding을 생성한다.
- sample Markdown 12개를 적재하고 동일 입력의 `unchanged=12`를 확인했다.
- 수정 문서만 새 version과 embedding을 생성하는 incremental ingestion을 확인했다.
- 일반 integration DB와 destructive migration DB를 분리하고 test 종료 시 base로 정리한다.
- 전체 test 63개, Ruff lint/format, `uv lock --check`, `git diff --check`가 통과했다.

현재 개발 DB 상태:

- Alembic revision: `0002 (head)`
- documents: 12
- current document versions: 12
- 모든 chunk embedding dimensions: 1024

Phase 3 상세 계획은
`docs/superpowers/plans/2026-07-27-phase-3-hybrid-retrieval.md`에 기록했다. Keyword search,
vector search, metadata filter, result fusion, source 반환까지만 Phase 3 범위로 다루며
OpenDART, Google ADK, Knowledge Workspace, provenance graph, Oracle Sync는 후속 Phase로
유지한다. 검색 계약과 Reciprocal Rank Fusion, PostgreSQL keyword/vector retrieval,
metadata filter, Hybrid Retrieval service, Query API와 source 응답까지 구현했다. 대표
질문용 sample 2개를 포함한 12개 문서를 실제 Ollama `bge-m3`로 적재했으며, Blueprint의
두 대표 질문이 각각 올바른 source를 최상위 결과로 반환하는 end-to-end 검증을 완료했다.

Phase 4 OpenDART는 재무 전용 PostgreSQL table 없이 구현한다. 종목코드와 사업연도로
사업·반기·1분기·3분기보고서의 CFS/OFS 전체 재무제표를 수집하고, 원본 JSON과 검색용
Markdown을 결정적으로 생성한 뒤 기존 ingestion을 재사용한다. 실행 진입점은
`uv run python -m scripts.collect_company_info --code <6자리 종목코드> --year <사업연도>`다.
전용 integration/migration test DB를 구성한 뒤 전체 test 75개가 skip 없이 통과했다.
OpenDART API key를 설정해 삼성전자 2025년 정기보고서 4개와 CFS/OFS 원본을 실제 수집했고,
재실행 시 `unchanged=4`를 확인했다. Hybrid Retrieval에서는 가장 최근 사업보고서의
연결 손익계산서가 1위로 반환되었으며 보고서명, 공시일, 핵심 수치와 접수번호 source
chain을 확인했다.

Phase 5 Google ADK는 기존 Hybrid Retrieval을 async Python Function Tool로 직접
연결한다. `search_knowledge`는 일반 지식을 검색하고 `query_financial_facts`는 별도
재무 table 없이 `domain=finance`, `source_type=opendart` 범위의 OpenDART Markdown을
검색한다. 기존 retrieval 전용 API였던 `POST /api/query`를 ADK 답변 endpoint로
전환했다. 버전 prefix가 있는
`POST /api/v1/query` alias는 제공하지 않는다. `local_only` 결과가 하나라도 있으면
본문과 metadata를 외부 모델에 전달하지 않고 고정된 정책 제한 답변을 반환한다. 격리된
integration/migration DB를 사용한 전체 test 125개가 통과했다. 실제 호스팅 Gemma
호출에서는 기술 질문이 `search_knowledge`를 사용해 6개 후보/source를 반환하고 근거
기반 답변을 생성하는 것을 확인했다. 재무 질문은 `query_financial_facts`를 사용해
`financial_hybrid` 경로와 최신 삼성전자 사업보고서 접수번호 `20260310002820`을
반환했다.

## Global Constraints

- 기준 설계 문서는 `docs/BLUEPRINT.md`다.
- Python 버전은 3.12로 고정하고 의존성과 `uv.lock`을 Git으로 관리한다.
- 비동기 I/O, SQLAlchemy 2.x 스타일, Pydantic v2, 타입 힌트를 사용한다.
- 설정과 모델명은 환경변수로 관리하고 비밀값 및 원본 데이터는 Git에 넣지 않는다.
- Phase 1–2에서는 Markdown 파일만 입력으로 받는다.
- OpenDART, Google ADK, Graphify, 검색 API, Hybrid Retrieval, Knowledge Workspace UI, Manifest/Artifact, Oracle Sync는 구현하지 않는다.
- 최소 구조를 유지하며 repository/service 계층을 기능별로 중복 생성하지 않는다.
- 구현은 각 Task의 테스트를 먼저 추가한 뒤 최소 코드로 통과시키는 순서로 진행한다.

---

## 1. 구현 시작 전 저장소 상태

- Git 브랜치: `main` (`origin/main` 추적)
- 추적되지 않은 파일: `.python-version`, `README.md`, `docs/BLUEPRINT.md`, `main.py`, `pyproject.toml`
- `.python-version`과 `pyproject.toml`은 현재 Python 3.13을 지정하므로 요구사항인 3.12로 변경해야 한다.
- `main.py`는 `Hello from second-brain!`만 출력하는 uv 초기화 파일이며 애플리케이션 코드로 재사용하지 않는다.
- `pyproject.toml`에는 런타임/개발 의존성과 도구 설정이 없다.
- `README.md`는 비어 있다.
- Docker Compose, 애플리케이션 패키지, 마이그레이션, 테스트, 샘플 지식 문서는 아직 없다.
- `.venv/`가 존재하지만 Git에서 제외되어 있다. 기존 환경의 Python 버전이 다를 수 있으므로 `uv sync`로 재생성 여부를 확인한다.

## 2. BLUEPRINT에서 발견한 불명확성 및 충돌

### 2.1 설계상 충돌

1. **Phase 2 저장 위치**
   - 전체 아키텍처는 로컬 PC가 Chunk/Embedding/Artifact를 만들고 Oracle이 패키지를 PostgreSQL에 반영한다고 설명한다.
   - Phase 2는 `Document 및 Chunk 저장`만 적고 어느 PostgreSQL에 저장하는지 명시하지 않는다.
   - **Phase 1–2 결정:** 개발용 로컬 PostgreSQL에 직접 저장한다. 패키지 Export와 Oracle Sync는 Phase 7에서 별도로 추가한다.

2. **Oracle의 질문 Embedding 실행 위치**
   - 로컬과 Oracle이 같은 Ollama Embedding 모델을 사용한다고 하지만, Oracle은 대형 로컬 LLM을 실행하지 않는다고 한다.
   - `bge-m3`의 Oracle 배치 위치, 자원 요구량, 원격 Ollama 허용 여부가 정해지지 않았다.
   - **Phase 1–2 결정:** `EmbeddingProvider`와 로컬 `OllamaEmbeddingProvider`만 구현한다. Oracle의 query embedding 토폴로지는 후속 검색/배포 설계에서 결정한다.

3. **`content_hash`의 자기 참조**
   - front matter 필수 필드에 `content_hash`가 있으면서 파이프라인이 `content_hash`를 생성한다고 한다. 파일 전체를 hash하면 front matter의 hash 값 자체 때문에 안정적인 값이 될 수 없다.
   - **Phase 1–2 결정:** front matter의 `content_hash`는 입력에서 선택 사항으로 받고 저장 시 계산값으로 대체한다. hash 입력은 UTF-8 LF로 정규화한 본문과 `content_hash`를 제외한 검증 완료 metadata의 canonical JSON이다.

4. **문서 ID와 DB ID**
   - front matter `id`, `documents.id`, `source_key`의 관계와 타입이 정의되지 않았다.
   - **Phase 1–2 결정:** DB 기본키는 UUID, front matter `id`는 `documents.source_key`에 저장하고 unique로 유지한다. Chunk ID 역시 UUID이며 재처리 중 생성되는 새 버전에 새 ID를 부여한다.

5. **`sources` 의존성**
   - 데이터 모델의 `documents.source_id`는 `sources`를 참조하지만 이번 요구 범위는 `Document`, `DocumentVersion`, `Chunk`뿐이다.
   - **Phase 1–2 결정:** `sources` 테이블을 미리 만들지 않는다. `documents.source_key`와 `metadata`에 출처 정보를 보존하고 Source 모델은 실제 두 번째 source adapter가 생길 때 추가한다.

6. **Phase 1 `/health` 범위**
   - 전체 `/health` 설계는 Google ADK, manifest, embedding version까지 요구하지만 이들은 Phase 1–2 범위 밖이다.
   - **Phase 1 결정:** API, PostgreSQL 연결, pgvector 확장 상태만 응답한다. DB/pgvector가 정상이 아니면 HTTP 503을 반환한다.

### 2.2 명세가 부족한 부분과 채택할 기본값

1. **Markdown 정규화:** BOM 제거, CRLF/CR을 LF로 통일, 각 줄의 trailing whitespace 제거, 문서 끝 newline 하나 보장만 수행한다. 의미가 바뀔 수 있는 공백/문단 재작성은 하지 않는다.
2. **Heading Chunker:** ATX heading(`#`~`######`)을 계층 경로로 추적한다. fenced code 내부의 `#`는 heading으로 보지 않는다. 한 section이 800 token 추정치를 넘으면 빈 줄 기준 문단으로 나누고, 100 token 이하의 앞 chunk 꼬리를 overlap한다. 표/코드 블록은 가능한 한 원자 블록으로 취급한다.
3. **Token 계산:** Phase 2에는 모델별 tokenizer를 추가하지 않고 공백/문장부호 기반의 결정적 추정 함수 하나를 사용한다. DB 필드는 이 추정값임을 코드 주석과 README에 밝힌다.
4. **Embedding 차원:** 초기 migration은 Blueprint 기본값인 1024차원의 `vector(1024)`를 사용한다. 설정의 차원이 1024가 아니거나 Ollama 응답 길이가 다르면 적재 전에 오류를 낸다.
5. **Ollama 호출 실패:** 제한된 timeout과 명시적 예외 변환만 구현한다. 자동 retry, fallback provider, 병렬 batch 조절은 실제 필요가 확인될 때 추가한다.
6. **삭제 처리:** 디렉터리 전체 동기화 및 soft delete는 Phase 7의 sync 범위다. Phase 2 단일/복수 파일 ingest는 누락 파일을 삭제로 간주하지 않는다.
7. **Knowledge Workspace와 출처 그래프:** URL, 텍스트, PDF, PPT 입력 UI 및 질문별 provenance graph는 Phase 6 범위다. Phase 1–2에서는 UI나 graph table을 만들지 않고, `Document → DocumentVersion → Chunk` FK, `source_path`, `heading_path`, 안정적인 ID를 통해 후속 provenance API가 출처 관계를 재구성할 수 있게 한다.
8. **동시 ingest:** 동일 문서를 여러 프로세스가 동시에 처리하는 운영 요건은 없다. DB unique constraint와 한 문서당 transaction으로 무결성을 지키되 분산 lock은 추가하지 않는다.

### 2.3 Clean Architecture 전환 시점

Blueprint는 `domain/application/infrastructure/interfaces` 구조를 제안하지만 특정 Phase의
일괄 전환을 요구하지 않는다. Phase 1–3은 Markdown ingestion과 retrieval만 있어 평면적인
기능 모듈이 더 작고 명확하므로 현재 구조를 유지한다.

Phase 4 OpenDART 착수 전에 점진적 전환을 시작한다. OpenDART에서 두 번째 source domain,
외부 API adapter, 정형 financial facts와 SQL/document retrieval 조합이 추가되는 시점부터
다음 경계가 실제 의존성 분리에 필요하기 때문이다.

- `domain`: Document, Chunk, retrieval 및 financial 규칙
- `application`: ingestion, hybrid retrieval, querying use case
- `infrastructure`: SQLAlchemy/PostgreSQL, Ollama, OpenDART adapter
- `interfaces`: FastAPI route와 CLI

Phase 4에서도 기존 파일을 한 번에 이동하지 않고, 새 OpenDART 기능과 함께 변경되는
모듈부터 이전한다. Phase 3 Task 5에는 이 구조 변경을 포함하지 않는다.

## 3. 생성·변경할 디렉터리와 파일

```text
.
├── .env.example                         # 비밀값 없는 설정 예시
├── .gitignore                           # raw/data/DB volume/환경 파일 제외
├── .python-version                      # 3.12
├── README.md                            # 개발 실행 및 ingest 사용법
├── PLAN.md                              # 이 구현 계획
├── alembic.ini
├── docker-compose.yml                   # PostgreSQL + pgvector
├── pyproject.toml
├── uv.lock
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI app factory
│   ├── api/
│   │   ├── __init__.py
│   │   └── health.py                    # /health
│   ├── config.py                        # pydantic-settings
│   ├── db.py                            # async engine/session
│   ├── models.py                        # Document/Version/Chunk ORM
│   ├── embeddings.py                    # Protocol + Ollama adapter
│   └── ingestion/
│       ├── __init__.py
│       ├── markdown.py                  # front matter/normalize/hash
│       ├── chunker.py                   # heading 기반 chunking
│       └── service.py                   # 증분 ingest transaction
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_create_knowledge_tables.py
├── scripts/
│   ├── __init__.py
│   └── ingest.py                        # Markdown ingest CLI
├── knowledge/
│   └── samples/                         # 유효한 샘플 Markdown 10개
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_markdown.py
    │   ├── test_chunker.py
    │   └── test_embeddings.py
    └── integration/
        ├── test_health.py
        └── test_ingestion.py
```

기존 루트 `main.py`는 `app/main.py`로 대체한 뒤 삭제한다. Phase 1–2에서 사용하지 않는 `domain/application/infrastructure/interfaces` 전체 계층, `collectors/`, `repositories/`, `manifests/`, `artifacts/`, `graphs/` 빈 디렉터리는 만들지 않는다.

## 4. 고정 인터페이스와 데이터 규칙

### 4.1 주요 Python 인터페이스

```python
@dataclass(frozen=True, slots=True)
class ParsedMarkdown:
    source_path: Path
    metadata: DocumentMetadata
    normalized_content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class ChunkData:
    chunk_index: int
    heading_path: tuple[str, ...]
    chunk_type: str
    chunk_text: str
    token_count: int
    content_hash: str


class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...

    @property
    def is_local(self) -> bool: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class IngestionResult(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


async def ingest_markdown(
    path: Path,
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
) -> IngestionResult: ...
```

### 4.2 데이터 모델

- `documents`
  - `id UUID PK`
  - `source_key VARCHAR UNIQUE NOT NULL` — front matter `id`
  - `source_path TEXT NOT NULL`
  - `title`, `source_type`, `document_type`, `domain` NOT NULL
  - `project`, `language`, `valid_from`, `valid_to` nullable
  - `access_scope`, `llm_policy` NOT NULL
  - `created_at`, `updated_at`, `observed_at` timezone-aware
  - `tags JSONB NOT NULL`, `metadata JSONB NOT NULL`
  - `is_deleted BOOLEAN NOT NULL DEFAULT false`
- `document_versions`
  - `id UUID PK`, `document_id UUID FK`
  - `version INTEGER`, 문서별 unique `(document_id, version)`
  - `content_path TEXT`, `normalized_content TEXT`
  - `content_hash VARCHAR(71)`, 문서별 unique `(document_id, content_hash)`
  - `created_at`, `is_current`
  - 문서별 current version 하나만 허용하는 partial unique index
- `chunks`
  - `id UUID PK`, `document_version_id UUID FK`, `parent_chunk_id UUID FK nullable`
  - `chunk_index INTEGER`, 버전별 unique `(document_version_id, chunk_index)`
  - `heading_path JSONB`, `chunk_type`, `chunk_text`, `token_count`
  - `content_hash VARCHAR(71)`, `metadata JSONB`, `embedding vector(1024)`, `created_at`

Phase 2에서는 parent-child chunk를 생성하지 않으므로 `parent_chunk_id`는 항상 null이지만 미래 migration 없이 계층 chunk를 추가할 수 있도록 Blueprint 필드를 보존한다.

Phase 6의 provenance graph는 이 FK 체인을 그대로 사용한다. 현재 단계에서는 `Question` 또는 retrieval trace를 저장하지 않으며, 검색 기능이 추가되는 Phase 3에서 질문별 후보 Chunk와 최종 사용 Chunk를 기록하는 데이터 계약을 설계한다.

### 4.3 증분 처리 transaction

1. Markdown을 읽고 파싱·검증·정규화·hash한다.
2. `source_key`로 Document와 current DocumentVersion을 조회한다.
3. current `content_hash`가 같으면 DB write와 Ollama 호출 없이 `UNCHANGED`를 반환한다.
4. 신규/변경 문서만 chunk하고 embedding한다.
5. embedding 개수 및 각 vector 차원을 검증한다.
6. 한 transaction에서 Document metadata를 upsert하고, 이전 version의 `is_current=false`, 다음 version 및 chunks를 insert한다.
7. 어느 단계든 실패하면 해당 문서 transaction 전체를 rollback하여 current version을 유지한다.

## 5. 구현 Task

### Task 1: Python 3.12 uv 프로젝트와 품질 도구

**Files:**
- Modify: `.python-version`
- Modify: `pyproject.toml`
- Create: `uv.lock`
- Modify: `.gitignore`
- Create: `.env.example`
- Modify: `README.md`
- Delete: `main.py`
- Create: `app/__init__.py`

**Produces:** 재현 가능한 Python 3.12 환경과 `uv run pytest`, `uv run ruff check .` 명령.

**Steps:**

- [x] `.python-version`과 `requires-python`을 `3.12`/`>=3.12,<3.13`으로 변경한다.
- [x] runtime 의존성에 `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pgvector`, `httpx`, `pyyaml`을 추가한다.
- [x] dev dependency group에 `pytest`, `pytest-asyncio`, `ruff`를 추가하고 pytest asyncio mode를 `auto`로 설정한다.
- [x] `.env.example`에 `DATABASE_URL`, `OLLAMA_BASE_URL`, `EMBEDDING_MODEL=bge-m3`, `EMBEDDING_DIMENSIONS=1024`, timeout 설정을 기록한다.
- [x] `.gitignore`에 Blueprint의 `raw/`, `data/`, `models/`, `cache/`, `tmp/`, `logs/`, `postgres-data/`, `ollama-data/`, `secrets/`, `credentials/`를 추가한다.
- [x] `uv lock`과 `uv sync --dev`를 실행한다.

**완료 조건:** Python 3.12 interpreter가 선택되고 의존성 lock이 생성되며 빈 테스트 수집과 Ruff가 성공한다.

**검증:**

```bash
uv run python --version
# Expected: Python 3.12.x

uv lock --check
# Expected: exit 0

uv run pytest --collect-only
# Expected: exit 0 (아직 테스트가 없다는 메시지는 허용)

uv run ruff check .
# Expected: All checks passed!
```

### Task 2: PostgreSQL + pgvector 개발 환경

**Files:**
- Create: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`

**Produces:** 이름 있는 volume, healthcheck, pgvector 지원 PostgreSQL 16 서비스.

**Steps:**

- [x] `pgvector/pgvector:pg16` 이미지의 `db` 서비스, 고정 개발용 DB/user/password, `5432` port, `pg_isready` healthcheck를 정의한다.
- [x] 비밀값 없는 로컬 기본 연결 문자열이 Compose와 `.env.example`에서 일치하게 한다.
- [x] README에 시작/종료/로그/데이터 초기화 명령을 기록하되 데이터 초기화는 명시적 파괴 작업임을 표시한다.
- [x] Compose 설정을 검증하고 DB를 시작한다.
- [x] `CREATE EXTENSION IF NOT EXISTS vector`가 이후 Alembic migration에서 수행될 수 있는지 접속으로 확인한다.

**완료 조건:** DB container가 healthy이고 PostgreSQL 접속이 가능하다.

**검증:**

```bash
docker compose config --quiet
# Expected: exit 0

docker compose up -d db
docker compose ps
# Expected: db service status contains "healthy"

docker compose exec -T db pg_isready -U second_brain -d second_brain
# Expected: accepting connections
```

### Task 3: 설정, Async DB session, FastAPI 앱과 `/health`

**Files:**
- Create: `app/config.py`
- Create: `app/db.py`
- Create: `app/main.py`
- Create: `app/api/__init__.py`
- Create: `app/api/health.py`
- Create: `tests/conftest.py`
- Create: `tests/integration/test_health.py`

**Consumes:** Task 1 환경 설정, Task 2 PostgreSQL.

**Produces:** `create_app() -> FastAPI`, `get_session()`, `GET /health`.

**Steps:**

- [x] settings cache를 test에서 초기화할 수 있고 환경변수로 DB/Ollama 설정을 읽는 실패 테스트를 작성한다.
- [x] DB가 정상일 때 `/health`가 `200`과 `{"status":"ok","database":"ok","pgvector":"ok"}`를 반환하는 integration test를 작성한다.
- [x] DB query가 실패하거나 `vector` extension이 없을 때 `/health`가 `503`과 component 상태를 반환하는 test를 작성한다.
- [x] `Settings`, async engine/session factory, FastAPI lifespan의 engine dispose를 최소 구현한다.
- [x] health handler에서 `SELECT 1`과 `pg_extension`의 `vector` 존재 여부를 확인한다.

**완료 조건:** 실행 중인 개발 DB에 대해 health 응답이 200이고 장애 상태가 503으로 구분된다.

**검증:**

```bash
uv run pytest tests/integration/test_health.py -v
# Expected: all tests passed

uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
# In another shell:
curl --fail http://127.0.0.1:8000/health
# Expected: {"status":"ok","database":"ok","pgvector":"ok"}
```

### Task 4: SQLAlchemy 모델과 첫 Alembic migration

**Files:**
- Create: `app/models.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_create_knowledge_tables.py`
- Create: `tests/integration/test_migrations.py`

**Produces:** `Document`, `DocumentVersion`, `Chunk` ORM 및 동일 구조의 migration.

**Steps:**

- [x] upgrade 시 extension/table/index/constraint가 존재하고 downgrade 시 앱 table만 제거되는 integration test를 작성한다.
- [x] timezone-aware timestamp와 UUID를 쓰는 세 ORM 모델 및 relationship을 정의한다.
- [x] migration에 `CREATE EXTENSION IF NOT EXISTS vector`, 세 table, FK cascade, unique constraints, current-version partial unique index를 명시적으로 작성한다.
- [x] Alembic async template를 설정하고 `DATABASE_URL`을 settings에서 읽게 한다.
- [x] 빈 DB에서 upgrade → downgrade → upgrade를 실행해 migration reversibility를 검증한다.

**완료 조건:** 새 DB에서 migration 하나로 pgvector와 세 table을 재현할 수 있고 ORM metadata와 schema가 일치한다.

**검증:**

```bash
uv run alembic upgrade head
uv run alembic current
# Expected: 0001 (head)

uv run pytest tests/integration/test_migrations.py -v
# Expected: all tests passed
```

### Task 5: YAML front matter parser, metadata validation, normalization, hash

**Files:**
- Create: `app/ingestion/__init__.py`
- Create: `app/ingestion/markdown.py`
- Create: `tests/unit/test_markdown.py`

**Produces:** `DocumentMetadata`, `ParsedMarkdown`, `parse_markdown(path)`, `normalize_markdown(text)`, `compute_content_hash(metadata, content)`.

**Steps:**

- [x] 유효한 한국어 Markdown과 timezone-aware 날짜/list/null 필드를 파싱하는 실패 테스트를 작성한다.
- [x] front matter 없음, 필수 key 없음, naive datetime, 종료 delimiter 없음, 빈 본문에 대한 구체적 validation error 테스트를 작성한다.
- [x] BOM/개행/trailing whitespace만 정규화하고 fenced code 및 본문 내부 공백은 보존하는 테스트를 작성한다.
- [x] metadata key 순서, CRLF, 입력 `content_hash` 값이 달라도 같은 canonical hash가 생성되는 테스트를 작성한다.
- [x] Pydantic v2 metadata 모델과 safe YAML parser를 최소 구현한다. 알 수 없는 metadata는 허용하여 `metadata` JSONB에 보존하되 필수 필드는 타입 검증한다.
- [x] `sha256:<64 lowercase hex>` 형식의 hash를 생성하고 입력 front matter hash와 불일치해도 계산값을 authoritative 값으로 사용한다.

**완료 조건:** 동일 의미의 입력은 안정적인 hash를 만들고 잘못된 문서는 DB/Ollama 이전 단계에서 명확히 거부된다.

**검증:**

```bash
uv run pytest tests/unit/test_markdown.py -v
# Expected: all tests passed
```

### Task 6: Markdown heading 기반 Chunker

**Files:**
- Create: `app/ingestion/chunker.py`
- Create: `tests/unit/test_chunker.py`

**Consumes:** Task 5 `ParsedMarkdown`.

**Produces:** `ChunkData`, `chunk_markdown(parsed, max_tokens=800, overlap_tokens=100)`.

**Steps:**

- [x] heading 계층(`# A` → `## B`)이 `("A", "B")`로 각 chunk에 저장되는 실패 테스트를 작성한다.
- [x] preamble, heading 없는 문서, 빈 section, fenced code의 `#`, 표가 있는 section의 테스트를 작성한다.
- [x] 800 token 초과 section이 문단 경계에서 분리되고 순서가 유지되며 100 token 이하 overlap이 생기는 테스트를 작성한다.
- [x] 같은 입력이 같은 chunk text/index/hash를 만드는 결정성 테스트를 작성한다.
- [x] 작은 state machine으로 fenced block과 heading을 구분하고, 논리 block을 token budget에 맞춰 조합하는 최소 구현을 작성한다.
- [x] embedding 입력에 문서 제목, domain, heading path, 본문을 포함하되 `chunk_text`에는 출처 추적 가능한 실제 본문을 보존한다.

**완료 조건:** 샘플의 모든 본문이 순서대로 chunk에 포함되고 heading path, index, hash, token_count가 결정적이다.

**검증:**

```bash
uv run pytest tests/unit/test_chunker.py -v
# Expected: all tests passed
```

### Task 7: Ollama Embedding Provider

**Files:**
- Create: `app/embeddings.py`
- Create: `tests/unit/test_embeddings.py`

**Consumes:** Task 1 settings.

**Produces:** `EmbeddingProvider`, `OllamaEmbeddingProvider`.

**Steps:**

- [x] HTTPX `MockTransport`로 model/text 목록을 Ollama endpoint에 보내고 입력 순서대로 vector를 반환하는 실패 테스트를 작성한다.
- [x] 빈 document 목록은 HTTP 호출 없이 빈 목록을 반환하는 테스트를 작성한다.
- [x] HTTP 오류, 잘못된 JSON, vector 개수 불일치, 1024가 아닌 vector를 각각 명시적 `EmbeddingError`로 변환하는 테스트를 작성한다.
- [x] 하나의 재사용 가능한 `httpx.AsyncClient`, model, dimensions, timeout을 주입받는 adapter를 최소 구현한다.
- [x] `embed_query`가 document와 동일 model/dimension 검증 경로를 사용하게 한다.

**완료 조건:** Provider가 네트워크 없이 단위 테스트 가능하고 모델/차원 불일치를 DB write 전에 차단한다.

**검증:**

```bash
uv run pytest tests/unit/test_embeddings.py -v
# Expected: all tests passed
```

### Task 8: 증분 Markdown ingestion service

**Files:**
- Create: `app/ingestion/service.py`
- Create: `tests/integration/test_ingestion.py`

**Consumes:** Task 4 ORM, Task 5 parser, Task 6 chunker, Task 7 Provider.

**Produces:** `ingest_markdown(...) -> IngestionResult`.

**Steps:**

- [x] 고정 vector를 반환하고 호출 횟수를 기록하는 test fake provider를 만든다.
- [x] 신규 파일 ingest가 Document 1, current Version 1, 예상 Chunk N개를 생성하고 metadata/source path/vector를 보존하는 실패 테스트를 작성한다.
- [x] 동일 파일의 두 번째 ingest가 `UNCHANGED`, row 수 불변, provider 추가 호출 0임을 검증한다.
- [x] 본문 수정 시 Document는 유지되고 Version 2와 새 Chunk/Embedding만 생성되며 Version 1은 보존·비활성화되는 테스트를 작성한다.
- [x] metadata만 수정해도 hash가 변경되고 새 version이 생기는 테스트를 작성한다.
- [x] embedding 실패/차원 오류 시 transaction이 rollback되고 기존 current version이 유지되는 테스트를 작성한다.
- [x] select → unchanged fast path → chunk/embed → single transaction upsert 순서로 최소 service를 구현한다.

**완료 조건:** content hash 기반의 create/update/no-op이 구분되고 수정 이력과 원자성이 보장된다.

**검증:**

```bash
uv run pytest tests/integration/test_ingestion.py -v
# Expected: all tests passed
```

### Task 9: CLI와 샘플 Markdown 10개

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/ingest.py`
- Create: `knowledge/samples/01-*.md` through `knowledge/samples/10-*.md`
- Modify: `README.md`

**Consumes:** Task 8 ingestion service.

**Produces:** `uv run python -m scripts.ingest <files-or-directories>` CLI.

**Steps:**

- [x] CLI가 파일과 디렉터리의 `*.md`를 정렬된 순서로 처리하고 결과별 count를 출력하는 test를 작성한다.
- [x] 경로 없음/유효 Markdown 없음/일부 문서 실패 시 non-zero exit와 파일별 오류를 반환하는 test를 작성한다.
- [x] 전역 transaction 하나 대신 문서별 transaction으로 10개를 처리하고 created/updated/unchanged/failed summary를 출력한다.
- [x] 서로 다른 heading, metadata, 한국어/영어, 표, code fence를 포함한 유효 샘플 10개를 작성한다. 실제 개인정보/자격 증명은 포함하지 않는다.
- [x] README에 DB/migration/Ollama 준비, ingest, 재실행, 수정 후 재실행 절차와 예상 결과를 기록한다.

**완료 조건:** 샘플 10개를 한 명령으로 적재하고 즉시 재실행하면 10개 모두 unchanged다.

**검증:**

```bash
uv run python -m scripts.ingest knowledge/samples
# Expected first run: created=10 updated=0 unchanged=0 failed=0

uv run python -m scripts.ingest knowledge/samples
# Expected second run: created=0 updated=0 unchanged=10 failed=0

docker compose exec -T db psql -U second_brain -d second_brain \
  -c "SELECT count(*) AS documents FROM documents; SELECT count(*) AS current_versions FROM document_versions WHERE is_current;"
# Expected: documents=10 and current_versions=10
```

### Task 10: Phase 1–2 전체 검증 및 문서 정합성

**Files:**
- Modify: `README.md`
- Modify only if verification finds an issue: files created in Tasks 1–9

**Consumes:** 모든 이전 Task.

**Produces:** 재현 가능한 완료 증거와 범위가 명확한 README.

**Steps:**

- [x] README의 clean-start 순서대로 DB 시작, migration, test, server health, sample ingest를 수행한다.
- [x] 전체 unit/integration test, Ruff check, Ruff format check를 실행한다.
- [x] DB에서 문서/version/chunk 수, `vector_dims(embedding)=1024`, current version uniqueness를 확인한다.
- [x] 샘플 하나의 복사본을 임시 경로에서 수정해 update를 확인하고 repository 샘플/DB 상태를 원복 가능한 방식으로 정리한다.
- [x] README에 Phase 1–2 범위와 제외 기능, `content_hash` 규칙, token_count가 추정값임을 기록한다.
- [x] `git diff --check`와 `git status --short`로 의도한 파일만 변경됐는지 검토한다.

**완료 조건:** 아래 명령들이 모두 성공하고 `/health`가 200이며 10개 샘플의 중복 없는 재적재가 입증된다.

**검증:**

```bash
docker compose config --quiet
uv lock --check
uv run alembic upgrade head
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
git diff --check
# Expected: every command exits 0

curl --fail http://127.0.0.1:8000/health
# Expected: HTTP 200 with api/database/pgvector healthy
```

## 6. Phase별 완료 기준

### Phase 1 완료

- Python 3.12와 `uv.lock`으로 환경이 재현된다.
- `docker compose up -d db` 후 PostgreSQL이 healthy다.
- Alembic이 pgvector extension 및 지식 테이블을 생성한다.
- FastAPI `/health`가 API/DB/pgvector 상태를 실제 검사한다.
- migration 및 health integration test가 통과한다.

### Phase 2 완료

- YAML front matter가 검증되고 Markdown이 보수적으로 정규화된다.
- heading 기반 chunk, heading path, 결정적 content hash가 생성된다.
- Ollama provider가 문서 embedding을 만들고 차원을 검증한다.
- 신규/동일/수정 문서가 각각 create/no-op/new-version으로 처리된다.
- 이전 version은 보존되고 하나의 current version만 유지된다.
- 샘플 10개 첫 적재와 중복 없는 재적재가 성공한다.
- 전체 test/Ruff/migration 검증이 통과한다.

## 7. 예상 위험과 완화

- **Ollama API/모델 가용성:** 실제 endpoint와 `bge-m3` 설치 여부가 환경마다 다르다. HTTP adapter는 mock 단위 테스트로 검증하고 실사용 검증은 README의 별도 prerequisite로 둔다.
- **Embedding 차원 불일치:** DB schema는 1024로 고정되므로 provider 응답과 설정을 insert 전에 검사하고 즉시 실패시킨다.
- **Markdown parser edge case:** YAML delimiter, code fence, 표, heading 유사 텍스트를 fixture로 고정해 회귀 테스트한다. 완전한 CommonMark AST parser는 현재 범위에 넣지 않는다.
- **Hash 규칙 변경:** canonicalization 규칙을 테스트와 README에 고정한다. 이후 규칙이 바뀌면 `content_version`/`chunker_version` 도입과 전체 재처리가 필요하다.
- **실 DB test 격리:** integration test는 전용 test database/schema를 사용하고 각 test를 rollback하거나 table truncate해 순서 의존성을 제거한다.
- **동시 갱신 race:** unique constraint가 데이터 중복을 차단하지만 분산 ingest lock은 없다. 운영 동시성이 실제 요구되면 advisory lock을 별도 변경으로 추가한다.
- **기존 미추적 파일:** 현재 파일은 사용자 작업일 수 있으므로 구현 시 내용을 확인하고 필요한 최소 변경만 수행하며, 자동 commit은 요청받기 전 하지 않는다.

## 8. 의도적으로 제외하는 후속 기능

- OpenDART collector/parser 및 `facts` 재무 모델
- Google ADK agent, Gemma 호출, `/api/v1/query`
- Graphify, entities, relationships, graph retrieval
- Keyword/vector/hybrid 검색과 metadata filter
- 질문 embedding 및 query router
- URL, 텍스트, PDF, PPT/PPTX 입력 adapter와 Knowledge Workspace UI
- 질문 → Chunk → DocumentVersion → Document → Source provenance graph
- Manifest, artifact export, Oracle Knowledge Sync, soft delete
- PDF/web/GitHub collector, OCR, 자동 Markdown 생성/요약
- 외부 LLM access-policy routing
- 인증, `/admin/sync`, UI, 배포/systemd/nginx

이 항목들은 현재 Task에 빈 interface, placeholder module, table로 미리 추가하지 않는다.

후속 Phase 6의 출처 그래프를 위해 Phase 1–2에서 보장하는 것은 문서/버전/Chunk의 FK 연결, 출처 경로, heading path, 안정적인 ID뿐이다. Entity 추출이나 Graphify용 관계 모델은 미리 도입하지 않는다.

## 9. 구현 순서 요약

```text
Python/uv
→ PostgreSQL/pgvector
→ FastAPI health + async DB
→ ORM/Alembic
→ Markdown parse/normalize/hash
→ heading chunk
→ Ollama embedding adapter
→ transactional incremental ingest
→ CLI + samples
→ end-to-end verification
```
