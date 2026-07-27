from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app.application.financial_files import (
    markdown_path,
    raw_path,
    write_json_atomic,
    write_text_atomic,
)
from app.application.render_financial_markdown import render_financial_markdown
from app.domain.financial import (
    REPORT_TYPES,
    FinancialReport,
    FinancialStatement,
    StatementType,
)
from app.infrastructure.opendart import OpenDartClient

Ingest = Callable[[Path], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    company_name: str
    stock_code: str
    business_year: int
    counts: dict[str, int]

    @property
    def failed(self) -> int:
        return self.counts.get("failed", 0)


async def collect_company_financials(
    *,
    client: OpenDartClient,
    stock_code: str,
    business_year: int,
    raw_dir: Path,
    markdown_dir: Path,
    dry_run: bool = False,
    ingest: Ingest | None = None,
) -> CollectionSummary:
    company = await client.find_company(stock_code)
    profile = await client.get_company(company.corp_code)
    disclosures = await client.list_disclosures(company, business_year)
    disclosure_by_receipt = {item.receipt_number: item for item in disclosures}
    counts: Counter[str] = Counter()

    if not dry_run:
        root = raw_dir / stock_code / str(business_year)
        write_json_atomic(root / "company.json", profile)
        write_json_atomic(
            root / "disclosures.json",
            {"list": [item.raw for item in disclosures]},
        )

    for report_type in REPORT_TYPES:
        statements: list[FinancialStatement] = []
        try:
            for statement_type in StatementType:
                statement = await client.get_statement(
                    company,
                    business_year,
                    report_type,
                    statement_type,
                )
                if statement is not None:
                    statements.append(statement)
            if not statements:
                # A complete 013 response can be transient. Preserve the last known report
                # instead of deleting already-ingested knowledge without an explicit delete API.
                counts["no_data"] += 1
                continue
            receipt_numbers = {item.receipt_number for item in statements}
            if len(receipt_numbers) != 1:
                raise ValueError(f"{report_type.code}: CFS/OFS receipt numbers do not match")
            receipt_number = receipt_numbers.pop()
            disclosure = disclosure_by_receipt.get(receipt_number)
            if disclosure is None:
                raise ValueError(f"{report_type.code}: disclosure {receipt_number} was not found")
            if dry_run:
                counts["unchanged"] += 1
                continue

            raw_changed = False
            present_types = {item.statement_type for item in statements}
            for statement_type in StatementType:
                stale_path = raw_path(
                    raw_dir,
                    stock_code,
                    business_year,
                    receipt_number,
                    statement_type.value,
                )
                if statement_type not in present_types and stale_path.exists():
                    stale_path.unlink()
                    raw_changed = True
            for statement in statements:
                raw_changed |= write_json_atomic(
                    raw_path(
                        raw_dir,
                        stock_code,
                        business_year,
                        receipt_number,
                        statement.statement_type.value,
                    ),
                    statement.raw,
                )
            report = FinancialReport(
                company=company,
                disclosure=disclosure,
                business_year=business_year,
                statements=tuple(statements),
            )
            output_path = markdown_path(
                markdown_dir,
                stock_code,
                business_year,
                receipt_number,
            )
            if raw_changed or not output_path.exists():
                write_text_atomic(
                    output_path,
                    render_financial_markdown(report),
                )
            if ingest is None:
                counts["created" if raw_changed else "unchanged"] += 1
            else:
                result = await ingest(output_path)
                counts[str(result)] += 1
        except Exception as exc:
            counts["failed"] += 1
            print(f"failed: report={report_type.code}: {exc}")

    return CollectionSummary(
        company_name=company.corp_name,
        stock_code=company.stock_code,
        business_year=business_year,
        counts=dict(counts),
    )
