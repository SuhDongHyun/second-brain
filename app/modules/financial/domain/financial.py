from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


@dataclass(frozen=True, slots=True)
class ReportType:
    """Identify an OpenDART periodic report and its display metadata.
    The immutable value maps an API code to stable storage and title values."""

    code: str
    slug: str
    title: str


REPORT_TYPES = (
    ReportType("11011", "annual", "사업보고서"),
    ReportType("11012", "semiannual", "반기보고서"),
    ReportType("11013", "quarter1", "1분기보고서"),
    ReportType("11014", "quarter3", "3분기보고서"),
)


class StatementType(StrEnum):
    """Enumerate consolidated and separate financial statement scopes.
    Values match the ``fs_div`` codes expected by OpenDART."""

    CFS = "CFS"
    OFS = "OFS"


@dataclass(frozen=True, slots=True)
class Company:
    """Represent a company resolved from the OpenDART corporation registry.
    Normalized identifiers are retained alongside the original registry item."""

    corp_code: str
    stock_code: str
    corp_name: str
    corp_eng_name: str
    modify_date: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Disclosure:
    """Represent one filed disclosure associated with a financial report.
    Parsed filing fields accompany the original OpenDART response item."""

    receipt_number: str
    report_name: str
    filed_at: date
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FinancialStatement:
    """Represent one consolidated or separate statement response.
    Rows and raw payload remain immutable for rendering and archival."""

    report_code: str
    statement_type: StatementType
    receipt_number: str
    rows: tuple[dict[str, Any], ...]
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FinancialReport:
    """Aggregate a company, disclosure, year, and available statements.
    The service passes this complete domain value to Markdown rendering."""

    company: Company
    disclosure: Disclosure
    business_year: int
    statements: tuple[FinancialStatement, ...]


def parse_amount(value: str | None) -> Decimal | None:
    """Convert an OpenDART amount string into a normalized decimal.
    Blank markers return ``None`` while malformed numeric values are rejected."""
    if value is None:
        return None
    normalized = value.strip().replace(",", "")
    if normalized in {"", "-"}:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"invalid financial amount: {value!r}") from exc
