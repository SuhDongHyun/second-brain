from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import yaml

from app.modules.financial.domain.financial import FinancialReport, StatementType

AMOUNT_COLUMNS = (
    ("thstrm_nm", "thstrm_amount"),
    ("thstrm_nm", "thstrm_add_amount"),
    ("frmtrm_nm", "frmtrm_amount"),
    ("frmtrm_q_nm", "frmtrm_q_amount"),
    ("frmtrm_q_nm", "frmtrm_add_amount"),
    ("bfefrmtrm_nm", "bfefrmtrm_amount"),
)


def _cell(value: object) -> str:
    """Escape a value for safe placement in a Markdown table cell.
    Empty values become a visible dash and line breaks are flattened."""
    return str(value or "-").replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _ordinal(row: dict[str, Any]) -> tuple[int, str]:
    """Build a stable statement-row sort key from ordinal and account name.
    Invalid ordinals fall back to zero without discarding the account label."""
    try:
        return int(str(row.get("ord", "0"))), str(row.get("account_nm", ""))
    except ValueError:
        return 0, str(row.get("account_nm", ""))


def _statement_sections(rows: tuple[dict[str, Any], ...]) -> list[str]:
    """Group OpenDART rows and render each statement as a Markdown table.
    Available period columns are discovered from the rows before sorting accounts."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("sj_div", "")), str(row.get("sj_nm", "재무제표")))].append(row)

    sections: list[str] = []
    for (_, statement_name), statement_rows in grouped.items():
        labels: list[tuple[str, str]] = []
        for name_key, amount_key in AMOUNT_COLUMNS:
            label = next(
                (str(row.get(name_key)) for row in statement_rows if row.get(name_key)),
                "",
            )
            if label and amount_key not in {key for _, key in labels}:
                labels.append((label, amount_key))
        header = ["계정"] + [label for label, _ in labels] + ["통화"]
        lines = [
            f"### {_cell(statement_name)}",
            "",
            "| " + " | ".join(header) + " |",
            "|" + "|".join(["---"] + ["---:" for _ in labels] + ["---"]) + "|",
        ]
        for row in sorted(statement_rows, key=_ordinal):
            cells = [_cell(row.get("account_nm"))]
            cells.extend(_cell(row.get(amount_key)) for _, amount_key in labels)
            cells.append(_cell(row.get("currency")))
            lines.append("| " + " | ".join(cells) + " |")
        sections.append("\n".join(lines))
    return sections


def render_financial_markdown(report: FinancialReport) -> str:
    """Render a financial report as an ingestible Markdown knowledge document.
    YAML provenance precedes human-readable disclosure details and statement tables."""
    disclosure = report.disclosure
    company = report.company
    timestamp = datetime.combine(
        disclosure.filed_at,
        datetime.min.time(),
        tzinfo=UTC,
    )
    tags = ["opendart", company.stock_code]
    metadata = {
        "id": f"opendart-{company.corp_code}-{disclosure.receipt_number}",
        "title": f"{company.corp_name} {disclosure.report_name}",
        "source_type": "opendart",
        "document_type": "financial_report",
        "domain": "finance",
        "language": "ko",
        "created_at": timestamp.isoformat(),
        "updated_at": timestamp.isoformat(),
        "observed_at": timestamp.isoformat(),
        "tags": tags,
        "access_scope": "public",
        "llm_policy": "external_allowed",
        "content_version": 1,
        "receipt_number": disclosure.receipt_number,
        "corp_code": company.corp_code,
        "stock_code": company.stock_code,
        "business_year": report.business_year,
    }
    front_matter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    lines = [
        "---",
        front_matter,
        "---",
        "",
        f"# {company.corp_name} {disclosure.report_name}",
        "",
        f"- 공시일: {disclosure.filed_at.isoformat()}",
        f"- 접수번호: {disclosure.receipt_number}",
        f"- 종목코드: {company.stock_code}",
        (f"- 원문: https://dart.fss.or.kr/dsaf001/main.do?rcpNo={disclosure.receipt_number}"),
    ]
    for statement in report.statements:
        title = (
            "연결재무제표 (CFS)"
            if statement.statement_type is StatementType.CFS
            else "별도재무제표 (OFS)"
        )
        lines.extend(["", f"## {title}", ""])
        lines.extend(_statement_sections(statement.rows))
    return "\n".join(lines).rstrip() + "\n"
