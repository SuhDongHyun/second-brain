import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.financial.domain.financial import (
    Company,
    Disclosure,
    FinancialReport,
    FinancialStatement,
    StatementType,
)
from app.modules.financial.infra.files import write_text_atomic
from app.modules.financial.service.render_financial_markdown import render_financial_markdown
from app.modules.knowledge.infra.models import Document, DocumentVersion
from app.modules.knowledge.service.ingest_markdown import IngestionResult, ingest_markdown

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required for OpenDART ingestion tests",
)


class FakeEmbeddingProvider:
    dimensions = 1024
    is_local = True

    def __init__(self) -> None:
        self.calls = 0

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[0.0] * self.dimensions for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.0] * self.dimensions


def report(amount: str) -> FinancialReport:
    company = Company("00126380", "005930", "삼성전자", "Samsung", "20250101", {})
    disclosure = Disclosure("20250318000984", "사업보고서 (2024.12)", date(2025, 3, 18), {})
    statement = FinancialStatement(
        "11011",
        StatementType.CFS,
        disclosure.receipt_number,
        (
            {
                "sj_div": "BS",
                "sj_nm": "재무상태표",
                "account_nm": "자산총계",
                "thstrm_nm": "제56기",
                "thstrm_amount": amount,
                "currency": "KRW",
                "ord": "1",
            },
        ),
        {},
    )
    return FinancialReport(company, disclosure, 2024, (statement,))


@pytest.mark.asyncio
async def test_generated_opendart_markdown_is_incrementally_ingested(
    migrated_test_database: str,
    tmp_path: Path,
) -> None:
    engine = create_async_engine(migrated_test_database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeEmbeddingProvider()
    path = tmp_path / "report.md"
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE TABLE documents CASCADE"))
        write_text_atomic(path, render_financial_markdown(report("100")))
        async with sessions() as session:
            assert await ingest_markdown(path, session, provider) == IngestionResult.CREATED
        async with sessions() as session:
            assert await ingest_markdown(path, session, provider) == IngestionResult.UNCHANGED

        write_text_atomic(path, render_financial_markdown(report("110")))
        async with sessions() as session:
            assert await ingest_markdown(path, session, provider) == IngestionResult.UPDATED

        async with sessions() as session:
            document = await session.scalar(select(Document))
            assert document is not None
            assert document.metadata_["receipt_number"] == "20250318000984"
            assert await session.scalar(select(func.count()).select_from(DocumentVersion)) == 2
        assert provider.calls == 2
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE TABLE documents CASCADE"))
        await engine.dispose()
