# Phase 4 OpenDART Design

## 1. Goal

종목코드와 사업연도를 입력하면 OpenDART에서 해당 기업의 사업보고서, 반기보고서,
1분기보고서, 3분기보고서 전체 재무제표를 수집한다. 연결재무제표와 별도재무제표를
구분한 원본 JSON을 보존하고, 기존 Markdown ingestion과 Hybrid Retrieval이 사용할
공시별 Markdown을 생성한다. Phase 4에서는 재무 전용 PostgreSQL table을 추가하지 않는다.

Phase 4의 완료 결과는 다음 명령으로 재현할 수 있어야 한다.

```bash
uv sync --frozen
uv run python -m scripts.collect_company_info --code 005930 --year 2025
```

`--year`를 생략하면 실행 시점의 현재 연도를 사용한다. 사용자는 하나의 CLI 진입점만
실행하지만, 내부 구현은 테스트와 유지보수를 위해 역할별 Python 모듈로 분리한다.

## 2. Scope

### Included

- OpenDART 전체 기업 고유번호 ZIP 다운로드와 종목코드 조회
- 선택한 기업의 기업개황 조회
- 선택한 사업연도의 정기공시 검색
- 보고서 코드 `11011`, `11012`, `11013`, `11014` 수집
- `CFS` 연결재무제표와 `OFS` 별도재무제표 구분
- 전체 재무제표의 계정, 기간, 금액, 통화와 원본 식별정보 보존
- OpenDART 원본 JSON의 결정적 경로 저장
- 공시별 Markdown 생성과 기존 ingestion 호출
- 실제 저장 없이 API 응답과 변환 결과를 검증하는 `--dry-run`
- 생성, 갱신, 변경 없음, 데이터 없음 건수 요약

### Excluded

- Google ADK와 자연어 답변 생성
- 여러 기업을 한 명령에서 일괄 수집하는 scheduler
- DART 원문 XBRL과 첨부파일 다운로드
- 임의 공시 및 비정기 공시 수집
- 재무 비율 계산과 투자 판단
- 재무 전용 PostgreSQL table과 SQL 집계
- 별도의 Web UI
- Oracle 배포와 Knowledge Package Sync

## 3. CLI Contract

실행 진입점은 `scripts/collect_company_info.py`이며 module mode로 실행한다.

```bash
uv run python -m scripts.collect_company_info --code 005930 --year 2025
uv run python -m scripts.collect_company_info --code 005930
uv run python -m scripts.collect_company_info --code 005930 --year 2025 --dry-run
```

입력 규칙:

- `--code`는 필수이며 정확히 숫자 6자리인 상장 종목코드다.
- `--year`는 선택이며 2015부터 현재 연도 사이의 4자리 연도다.
- `--dry-run`에서는 OpenDART 조회와 정규화까지 수행하지만 DB, 파일, Ollama를 변경하지
  않는다.
- API key는 `OPENDART_API_KEY` 환경변수 또는 `.env`에서 읽으며 CLI 인자로 받지 않는다.

종료 코드는 성공 `0`, 입력 오류 `2`, OpenDART/DB/ingestion 실패 `1`로 구분한다.
성공 시 기업명, 사업연도, 보고서별 CFS/OFS 상태와 created/updated/unchanged/no-data
요약을 출력한다.

## 4. Architecture

Phase 1–3의 기존 파일을 일괄 이동하지 않는다. Phase 4에서 새로 추가되는 기능부터
Clean Architecture 경계를 적용한다.

```text
scripts/collect_company_info.py
  -> app/application/collect_company_financials.py
     -> app/infrastructure/opendart.py
     -> app/domain/financial.py
     -> app/application/render_financial_markdown.py
     -> app/ingestion/service.py
```

- `domain/financial.py`: 보고서 종류, 재무제표 구분, 정규화된 immutable data contract,
  금액 파싱 규칙을 소유한다.
- `infrastructure/opendart.py`: HTTPX client, ZIP/XML 파싱, JSON 응답 상태 검증과 OpenDART
  endpoint adapter를 소유한다.
- `application/render_financial_markdown.py`: 정규화된 공시를 결정적인 Markdown으로
  변환한다.
- `application/collect_company_financials.py`: 조회, 정규화, raw/Markdown 저장, ingestion
  순서를 조율하며 외부 세부사항을 직접 구현하지 않는다.
- `scripts/collect_company_info.py`: 인자 검증, dependency 구성, 결과 출력과 exit code만
  담당한다.

## 5. OpenDART Data Flow

1. `corpCode.xml` ZIP을 받아 XML 목록에서 `stock_code`가 CLI 입력과 같은 기업을 찾는다.
2. `company.json`으로 기업개황을 조회한다.
3. `list.json`에 `corp_code`, 선택 연도의 날짜 범위, 정기공시 유형을 적용해 공시
   접수번호와 정확한 보고서명을 확인한다.
4. 네 보고서 코드 각각에 대해 `fnlttSinglAcntAll.json`을 `CFS`, `OFS` 순서로 조회한다.
5. OpenDART 응답의 기업, 보고서, 재무제표, 계정과 기간 값을 domain contract로
   정규화한다.
6. API key를 제외한 원본 응답을 결정적인 JSON 파일로 저장한다.
7. 공시별 CFS/OFS 내용을 하나의 Markdown 문서로 생성하고 기존 ingestion service를
   호출한다.

OpenDART 상태 `013`은 해당 조합에 자료가 없음을 뜻하는 정상 `no-data` 결과로 처리한다.
인증 실패, 호출 제한, 점검, 알 수 없는 상태와 schema 불일치는 실패로 처리한다.

## 6. File Layout and Idempotency

원본과 생성 Markdown은 다음 경로에 저장한다.

```text
raw/opendart/<stock-code>/<year>/
  company.json
  disclosures.json
  <receipt-number>-CFS.json
  <receipt-number>-OFS.json

knowledge/generated/opendart/<stock-code>/<year>/
  <receipt-number>.md
```

- JSON은 key 정렬, UTF-8, LF와 안정적인 들여쓰기를 사용해 같은 응답이 같은 file content를
  만들게 한다.
- API key는 원본 파일과 hash 입력에서 제외한다.
- JSON과 Markdown은 임시 파일에 쓴 뒤 같은 filesystem에서 원자적으로 교체한다.
- 같은 명령을 재실행하면 같은 경로를 갱신하며 중복 파일을 만들지 않는다.
- 정정공시는 새 접수번호의 별도 JSON과 Markdown으로 보존한다.
- 동일 보고서 코드에 접수번호가 여럿이면 공시일과 접수번호가 가장 최근인 자료를 현재
  요약 대상으로 선택하되 이전 접수도 삭제하지 않는다.
- 기존 ingestion을 매번 호출해 누락되거나 실패했던 적재를 복구한다. Markdown 내용이
  같으면 기존 content hash 비교가 DocumentVersion, Ollama 호출과 embedding 생성을
  건너뛴다.
- 한 보고서 실패가 이미 완료된 다른 보고서 파일과 ingestion 결과를 훼손하지 않지만
  CLI는 부분 실패를 명시하고 exit `1`로 종료한다.

## 7. Markdown Contract

공시 접수번호별 문서 하나를 만들고 CFS/OFS section을 모두 포함한다.

```yaml
---
id: "opendart-00126380-20250318000984"
title: "삼성전자 2024년 사업보고서"
source_type: "opendart"
document_type: "financial_report"
domain: "finance"
language: "ko"
created_at: "<공시일 00:00:00+09:00>"
updated_at: "<공시일 00:00:00+09:00>"
observed_at: "<공시일 00:00:00+00:00>"
tags: ["opendart", "005930", "annual-report"]
access_scope: "public"
llm_policy: "external_allowed"
content_version: 1
receipt_number: "20250318000984"
corp_code: "00126380"
stock_code: "005930"
business_year: 2024
---
```

본문에는 보고서명, 공시일, 접수번호, 기업 식별정보와 CFS/OFS별 재무상태표,
손익계산서, 현금흐름표의 계정 표를 넣는다. OpenDART의 모든 항목은 raw JSON에 보존하고,
Markdown은 검색 품질과 문서 크기를 위해 statement별 계정 표로 결정적으로 구성한다.
`observed_at`은 재실행 시 content hash가 달라지지 않도록 안정적인 원본 공시일을 사용한다.

## 8. Configuration and Portability

`.env.example`에 다음 설정을 추가한다.

```env
OPENDART_API_KEY=
OPENDART_BASE_URL=https://opendart.fss.or.kr/api
OPENDART_TIMEOUT_SECONDS=30
OPENDART_RAW_DIR=raw/opendart
OPENDART_MARKDOWN_DIR=knowledge/generated/opendart
```

API key는 로그, 예외 메시지, raw JSON과 hash 입력에 포함하지 않는다. 원본 API 응답은
`raw/opendart/`에 저장하고 Git에서 제외한다. 다른 Linux PC에서는 저장소, `uv.lock`,
`.env`를 옮기고 `uv sync --frozen`을 실행하면 같은 CLI를 사용할 수 있다. PostgreSQL과
Ollama는 기존 프로젝트와 동일하게 외부 서비스로 실행되어 있어야 한다.

## 9. Error Handling

- 존재하지 않는 종목코드는 API 호출 전에 명확한 validation error로 종료한다.
- HTTP timeout, transport error와 OpenDART 상태 코드를 `OpenDartError` 하위 예외로
  변환한다.
- 응답에 예상 필드가 없거나 숫자 변환이 불가능하면 접수번호와 계정 정보를 포함하되
  API key는 제외한 오류를 반환한다.
- 상태 `013`은 실패가 아니라 `no-data`로 집계한다.
- raw JSON 또는 Markdown 쓰기가 실패하면 해당 파일의 기존 버전을 유지한다.
- ingestion 실패 시 생성 파일은 유지해 다음 실행에서 ingestion을 재시도할 수 있게 한다.

## 10. Testing and Completion

단위 테스트:

- 기업 ZIP/XML 파싱과 종목코드 lookup
- OpenDART 상태와 HTTP 오류 매핑
- 네 보고서 코드와 CFS/OFS 요청 인자
- 쉼표, 음수, 빈 값, `-`, 계정 ID 누락 금액 정규화
- 결정적 raw hash와 Markdown 출력
- CLI 입력, 기본 연도, dry-run, exit code

통합 테스트:

- 새 기업과 공시의 raw JSON 및 Markdown 생성
- 같은 응답 재실행 시 파일 내용과 DocumentVersion/embedding 불변
- 변경된 응답만 Markdown과 DocumentVersion 갱신
- `013` CFS와 정상 OFS 혼합 처리
- ingestion 후 Hybrid Retrieval source가 접수번호까지 추적 가능

실환경 완료 검증:

```bash
uv run python -m scripts.collect_company_info --code 005930 --year <검증연도>
```

삼성전자의 해당 연도 정기공시를 수집한 뒤 가장 최근 연결재무제표에 대해 정확한
보고서명, 공시일, `CFS`, 핵심 재무 수치, 접수번호를 raw JSON, 생성 Markdown과 기존
Document/Chunk 저장소에서 확인한다.
전체 pytest, Ruff lint/format, lockfile과 diff 검사도 통과해야 한다.

## 11. Implementation Sequence

1. Phase 4 설정, domain contract와 OpenDART client
2. 원본 JSON writer와 Markdown renderer
3. 기존 ingestion 연결
4. `collect_company_info.py` CLI orchestration
5. 삼성전자 실환경 end-to-end 검증과 문서화
