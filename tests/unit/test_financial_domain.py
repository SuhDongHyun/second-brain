from datetime import date
from decimal import Decimal

from app.domain.financial import (
    REPORT_TYPES,
    Company,
    Disclosure,
    FinancialReport,
    FinancialStatement,
    StatementType,
    parse_amount,
)


def test_report_and_statement_types_are_fixed() -> None:
    assert [(item.code, item.slug) for item in REPORT_TYPES] == [
        ("11011", "annual"),
        ("11012", "semiannual"),
        ("11013", "quarter1"),
        ("11014", "quarter3"),
    ]
    assert [item.value for item in StatementType] == ["CFS", "OFS"]


def test_parse_amount_normalizes_opendart_values() -> None:
    assert parse_amount("1,234") == Decimal("1234")
    assert parse_amount("-42") == Decimal("-42")
    assert parse_amount("") is None
    assert parse_amount("-") is None
    assert parse_amount(None) is None


def test_financial_contract_composes_company_disclosure_and_statements() -> None:
    company = Company("00126380", "005930", "삼성전자", "Samsung Electronics", "20250101", {})
    disclosure = Disclosure(
        receipt_number="20250318000984",
        report_name="사업보고서 (2024.12)",
        filed_at=date(2025, 3, 18),
        raw={},
    )
    statement = FinancialStatement(
        report_code="11011",
        statement_type=StatementType.CFS,
        receipt_number=disclosure.receipt_number,
        rows=(),
        raw={},
    )

    report = FinancialReport(company, disclosure, 2024, (statement,))

    assert report.company.stock_code == "005930"
    assert report.statements[0].statement_type is StatementType.CFS
