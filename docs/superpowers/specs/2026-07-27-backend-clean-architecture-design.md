# Backend Clean Architecture Refactoring Design

## 목적

`docs/clean_architecture_guide.md`의 원칙에 맞게 `app/` 백엔드를 업무 기능 중심의
Clean Architecture 구조로 재배치한다. 기존 HTTP API, CLI, 데이터베이스 schema,
외부 연동 동작은 유지하고 내부 책임과 의존성만 명확히 한다.

프로젝트는 소규모 서비스이므로 가이드 10번을 적용한다. 구현체가 하나뿐인 기능을
위해 별도 Port 인터페이스나 DI container 라이브러리를 추가하지 않고, 작은
composition 함수에서 구체 객체를 생성해 service에 주입한다.

## 범위

리팩토링 대상은 다음 세 업무 영역이다.

- Knowledge: Markdown parsing, chunking, embedding, ingestion, hybrid retrieval
- Financial: OpenDART 조회, 재무 도메인 모델, Markdown 렌더링, 파일 저장
- Health: API와 PostgreSQL/pgvector 상태 확인

`app/config.py`, 데이터베이스 engine/session 생성, FastAPI application 조립은
애플리케이션 공통 진입점에 둔다. `scripts/`와 `tests/`는 새 import 경로와 조립
방식을 사용하도록 함께 수정한다.

다음은 변경하지 않는다.

- `GET /health`, `POST /api/v1/query`의 경로와 HTTP 계약
- CLI의 argument, exit code, 출력 형식
- SQLAlchemy table과 column 정의 및 Alembic migration
- OpenDART 요청·검증 규칙
- Markdown metadata, chunking, content hash, ingestion versioning 규칙
- keyword/vector 검색과 Reciprocal Rank Fusion 결과
- 설정 환경 변수 이름과 기본값

## 구조

```text
app/
├── main.py
├── composition.py
├── config.py
├── db.py
└── modules/
    ├── knowledge/
    │   ├── domain/
    │   │   ├── document.py
    │   │   └── retrieval.py
    │   ├── service/
    │   │   ├── chunk_markdown.py
    │   │   ├── ingest_markdown.py
    │   │   └── search_knowledge.py
    │   ├── infra/
    │   │   ├── embedding.py
    │   │   ├── models.py
    │   │   └── retrieval.py
    │   └── interface/
    │       ├── controller.py
    │       └── schema.py
    ├── financial/
    │   ├── domain/
    │   │   └── financial.py
    │   ├── service/
    │   │   ├── collect_company_financials.py
    │   │   └── render_financial_markdown.py
    │   └── infra/
    │       ├── files.py
    │       └── opendart.py
    └── health/
        └── interface/
            ├── controller.py
            └── schema.py
```

각 `__init__.py`는 package 표시에만 사용하며 다른 모듈의 symbol을 다시 export하지
않는다. 파일명은 기술적인 `service.py`, `models.py`보다 책임이 드러나는 이름을
우선한다. SQLAlchemy persistence model은 역할상 `knowledge/infra/models.py`에
둔다.

## 계층 책임과 의존성

### Domain

표준 라이브러리와 순수 Python 타입으로 업무 데이터를 표현한다. Financial
domain과 검색 결과 model은 FastAPI, SQLAlchemy, HTTPX를 import하지 않는다.
Markdown 입력 검증은 파일 경계의 parsing 책임과 Pydantic metadata validation이
밀접하므로 Knowledge domain의 document module에 함께 둔다. 이 실용적 예외가
HTTP schema나 infrastructure model을 domain으로 유입시키지는 않는다.

### Service

사용자 작업 단위의 흐름과 순수 계산을 담당한다. Ingestion service는 parsing,
chunking, embedding, persistence 순서를 조정한다. Search service는 query
embedding, 두 검색 방식 실행, RRF 결합을 조정한다. Financial collection
service는 OpenDART 조회, rendering, 파일 저장, 선택적인 ingestion callback을
조정한다.

가이드 10번에 따라 service가 사용하는 concrete dependency type은 별도 Port로
감싸지 않는다. 의존 객체는 module import 시 생성하지 않고 함수 parameter나
constructor로 전달한다. 순수 계산 함수는 외부 객체에 의존하지 않는다.

### Infrastructure

Ollama HTTP 요청, OpenDART HTTP 요청, SQLAlchemy persistence/query, filesystem
write를 담당한다. 외부 오류는 현재 공개된 application-specific exception으로
변환하는 기존 계약을 유지한다. SQLAlchemy entity가 controller response로 직접
노출되지 않도록 retrieval 경계에서 domain result로 변환한다.

### Interface

FastAPI controller와 Pydantic request/response schema를 분리한다. Controller는
dependency 수신, service 호출, domain-to-response mapping만 수행한다. Query
validation은 HTTP 입력에 관한 규칙이면 schema에, HTTP와 무관한 service
invariant이면 service에 둔다.

### Composition Root

`app/composition.py`는 설정을 바탕으로 Ollama embedding 구현과 service
dependency를 조립한다. 별도 container package나 provider framework는 사용하지
않는다. FastAPI lifespan은 조립된 장기 생존 resource를 `application.state`에
보관하고 종료 시 HTTP client와 DB engine을 닫는다.

CLI는 FastAPI composition을 역으로 참조하지 않는다. 각 CLI의 `run()` 진입점이
동일한 설정과 infrastructure class를 사용해 필요한 객체를 명시적으로 조립한다.
객체 생성은 CLI 진입부에 머물고 업무 흐름은 service에 둔다.

## 요청 및 데이터 흐름

Query 요청은 다음 순서로 처리한다.

```text
Query schema
  → Query controller
  → Search knowledge service
  → Ollama embedding + SQLAlchemy retrieval
  → Retrieval domain result
  → Query response schema
```

Markdown ingestion은 다음 순서로 처리한다.

```text
CLI 또는 Financial collection service
  → Ingest Markdown service
  → Markdown parse + chunk calculation
  → Ollama embedding
  → SQLAlchemy transaction
```

OpenDART 수집은 다음 순서로 처리한다.

```text
CLI
  → Collect company financials service
  → OpenDART infrastructure
  → Financial domain model
  → Markdown renderer
  → Filesystem infrastructure
  → optional Ingest Markdown service
```

## 오류 처리

기존 오류 type과 observable behavior를 보존한다.

- 잘못된 Markdown은 `MarkdownValidationError`로 보고한다.
- embedding 실패와 local-only 위반은 `EmbeddingError`로 보고한다.
- OpenDART 오류는 `OpenDartError` 계열로 보고한다.
- Query embedding 오류는 기존과 같이 HTTP 503으로 변환한다.
- Query 입력 검증 오류는 기존 FastAPI/Pydantic 422 계약을 유지한다.
- Health dependency 실패는 component status를 포함한 HTTP 503 응답으로
  변환한다.
- transaction과 atomic file write semantics는 변경하지 않는다.

Infrastructure-specific exception을 controller가 직접 처리해야 하는 새로운
결합은 만들지 않는다.

## 테스트 전략

리팩토링 전 전체 test 결과를 기준선으로 기록한다. 파일 이동은 작은 단위로
진행하며 각 단위마다 관련 unit test를 새 import 경로로 갱신한다.

- Domain과 순수 계산: 기존 unit test를 새 module에 연결
- Ollama/OpenDART adapter: 기존 HTTP mock 기반 unit test 유지
- Ingestion/retrieval: 기존 PostgreSQL integration test 유지
- Controller: dependency override와 response contract test 유지
- CLI: argument, 조립, summary, exit code test 유지
- Architecture: domain이 FastAPI, SQLAlchemy, HTTPX와 같은 외부 계층을
  import하지 않고 legacy module이 남지 않는지 검사하는 test 추가

완료 전 다음 명령을 새로 실행한다.

```bash
uv lock --check
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```

PostgreSQL integration test 실행에 필요한 안전한 test database가 현재 환경에
없다면 해당 사실과 미실행 범위를 최종 결과에 명시한다. 가능한 unit test와
정적 검사는 반드시 모두 실행한다.

## 마이그레이션과 정리

새 module로 이동한 뒤 `app/api`, `app/application`, `app/domain`,
`app/infrastructure`, `app/ingestion`, `app/embeddings.py`, `app/models.py`,
`app/retrieval.py`의 legacy source는 제거한다. 호환용 re-export module은
유지하지 않는다.

테스트와 script는 새 경로를 직접 import한다. 변경 과정에서 사용자 소유의
untracked 파일이나 관련 없는 working-tree 변경은 수정하거나 commit하지 않는다.

## 수용 기준

- 기존 HTTP, CLI, database, OpenDART, Markdown, retrieval 동작이 유지된다.
- 코드는 Knowledge, Financial, Health 업무 module로 탐색할 수 있다.
- Domain model과 HTTP schema, SQLAlchemy model이 분리된다.
- Controller에 업무 계산이나 concrete client 생성이 없다.
- Concrete dependency 생성은 composition root 또는 CLI entry point에 있다.
- 별도 Port interface와 DI container dependency를 추가하지 않는다.
- Legacy backend module과 legacy import가 남지 않는다.
- 관련 test와 정적 검사가 통과하거나, 환경 dependency로 실행하지 못한 검증이
  정확히 보고된다.
