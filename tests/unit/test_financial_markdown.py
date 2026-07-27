from datetime import date
from pathlib import Path

from app.application.render_financial_markdown import render_financial_markdown
from app.domain.financial import (
    Company,
    Disclosure,
    FinancialReport,
    FinancialStatement,
    StatementType,
)
from app.ingestion.markdown import parse_markdown


def test_renderer_creates_ingestible_markdown_with_sources(tmp_path: Path) -> None:
    company = Company("00126380", "005930", "삼성전자", "Samsung", "20250101", {})
    disclosure = Disclosure("20250318000984", "사업보고서 (2024.12)", date(2025, 3, 18), {})
    row = {
        "sj_div": "BS",
        "sj_nm": "재무상태표",
        "account_nm": "자산|총계",
        "thstrm_nm": "제56기",
        "thstrm_amount": "100,000",
        "frmtrm_nm": "제55기",
        "frmtrm_amount": "90,000",
        "currency": "KRW",
        "ord": "1",
    }
    statements = tuple(
        FinancialStatement("11011", kind, disclosure.receipt_number, (row,), {})
        for kind in StatementType
    )
    rendered = render_financial_markdown(FinancialReport(company, disclosure, 2024, statements))
    path = tmp_path / "report.md"
    path.write_text(rendered, encoding="utf-8")

    parsed = parse_markdown(path)
    assert parsed.metadata.id == "opendart-00126380-20250318000984"
    assert parsed.metadata.observed_at.isoformat() == "2025-03-18T00:00:00+00:00"
    assert "## 연결재무제표 (CFS)" in rendered
    assert "## 별도재무제표 (OFS)" in rendered
    assert "자산\\|총계" in rendered
    assert "20250318000984" in rendered
