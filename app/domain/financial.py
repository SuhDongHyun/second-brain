from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


@dataclass(frozen=True, slots=True)
class ReportType:
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
    CFS = "CFS"
    OFS = "OFS"


@dataclass(frozen=True, slots=True)
class Company:
    corp_code: str
    stock_code: str
    corp_name: str
    corp_eng_name: str
    modify_date: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Disclosure:
    receipt_number: str
    report_name: str
    filed_at: date
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FinancialStatement:
    report_code: str
    statement_type: StatementType
    receipt_number: str
    rows: tuple[dict[str, Any], ...]
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FinancialReport:
    company: Company
    disclosure: Disclosure
    business_year: int
    statements: tuple[FinancialStatement, ...]


def parse_amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    normalized = value.strip().replace(",", "")
    if normalized in {"", "-"}:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"invalid financial amount: {value!r}") from exc
