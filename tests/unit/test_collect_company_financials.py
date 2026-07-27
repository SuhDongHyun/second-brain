from datetime import date
from pathlib import Path

import pytest

from app.application.collect_company_financials import collect_company_financials
from app.domain.financial import (
    REPORT_TYPES,
    Company,
    Disclosure,
    FinancialStatement,
    StatementType,
)


class FakeClient:
    calls: list[tuple[str, str]]

    def __init__(self) -> None:
        self.calls = []
        self.company = Company("00126380", "005930", "삼성전자", "Samsung", "20250101", {})
        self.receipt = "20250318000984"
        self.missing_types: set[StatementType] = set()

    async def find_company(self, stock_code: str) -> Company:
        return self.company

    async def get_company(self, corp_code: str) -> dict[str, str]:
        return {"status": "000", "corp_name": "삼성전자"}

    async def list_disclosures(self, company: Company, year: int) -> list[Disclosure]:
        return [Disclosure(self.receipt, "사업보고서 (2024.12)", date(2025, 3, 18), {})]

    async def get_statement(
        self, company: Company, year: int, report_type: object, statement_type: StatementType
    ) -> FinancialStatement | None:
        self.calls.append((report_type.code, statement_type.value))
        if report_type != REPORT_TYPES[0] or statement_type in self.missing_types:
            return None
        return FinancialStatement(
            report_type.code,
            statement_type,
            self.receipt,
            (
                {
                    "sj_div": "BS",
                    "sj_nm": "재무상태표",
                    "account_nm": "자산총계",
                    "thstrm_nm": "당기",
                    "thstrm_amount": "100",
                },
            ),
            {"status": "000", "list": []},
        )


@pytest.mark.asyncio
async def test_collection_queries_all_types_and_is_idempotent(tmp_path: Path) -> None:
    client = FakeClient()
    ingested: list[Path] = []

    async def ingest(path: Path) -> str:
        ingested.append(path)
        return "created" if len(ingested) == 1 else "unchanged"

    first = await collect_company_financials(
        client=client,
        stock_code="005930",
        business_year=2025,
        raw_dir=tmp_path / "raw",
        markdown_dir=tmp_path / "md",
        ingest=ingest,
    )
    second = await collect_company_financials(
        client=client,
        stock_code="005930",
        business_year=2025,
        raw_dir=tmp_path / "raw",
        markdown_dir=tmp_path / "md",
        ingest=ingest,
    )

    assert len(client.calls) == 16
    assert first.counts == {"created": 1, "no_data": 3}
    assert second.counts == {"unchanged": 1, "no_data": 3}
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 4
    assert len(list((tmp_path / "md").rglob("*.md"))) == 1


@pytest.mark.asyncio
async def test_dry_run_does_not_write_or_ingest(tmp_path: Path) -> None:
    summary = await collect_company_financials(
        client=FakeClient(),
        stock_code="005930",
        business_year=2025,
        raw_dir=tmp_path / "raw",
        markdown_dir=tmp_path / "md",
        dry_run=True,
    )

    assert summary.counts == {"unchanged": 1, "no_data": 3}
    assert not tmp_path.joinpath("raw").exists()


@pytest.mark.asyncio
async def test_collection_removes_statement_that_is_no_longer_returned(tmp_path: Path) -> None:
    client = FakeClient()

    async def ingest(path: Path) -> str:
        return "updated"

    arguments = {
        "client": client,
        "stock_code": "005930",
        "business_year": 2025,
        "raw_dir": tmp_path / "raw",
        "markdown_dir": tmp_path / "md",
        "ingest": ingest,
    }
    await collect_company_financials(**arguments)
    client.missing_types.add(StatementType.CFS)

    summary = await collect_company_financials(**arguments)

    raw_files = {path.name for path in (tmp_path / "raw").rglob("*.json")}
    markdown = next((tmp_path / "md").rglob("*.md")).read_text(encoding="utf-8")
    assert "20250318000984-CFS.json" not in raw_files
    assert "20250318000984-OFS.json" in raw_files
    assert "## 연결재무제표 (CFS)" not in markdown
    assert "## 별도재무제표 (OFS)" in markdown
    assert summary.counts == {"updated": 1, "no_data": 3}


@pytest.mark.asyncio
async def test_collection_preserves_last_known_report_when_all_statements_are_no_data(
    tmp_path: Path,
) -> None:
    client = FakeClient()

    async def ingest(path: Path) -> str:
        return "created"

    arguments = {
        "client": client,
        "stock_code": "005930",
        "business_year": 2025,
        "raw_dir": tmp_path / "raw",
        "markdown_dir": tmp_path / "md",
        "ingest": ingest,
    }
    await collect_company_financials(**arguments)
    raw_before = {path.name: path.read_bytes() for path in (tmp_path / "raw").rglob("*.json")}
    markdown_path = next((tmp_path / "md").rglob("*.md"))
    markdown_before = markdown_path.read_bytes()
    client.missing_types.update(StatementType)

    summary = await collect_company_financials(**arguments)

    assert {
        path.name: path.read_bytes() for path in (tmp_path / "raw").rglob("*.json")
    } == raw_before
    assert markdown_path.read_bytes() == markdown_before
    assert summary.counts == {"no_data": 4}
