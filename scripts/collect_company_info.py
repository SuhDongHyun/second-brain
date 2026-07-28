from __future__ import annotations

import argparse
import asyncio
from datetime import date
from pathlib import Path

from app.config import get_settings
from app.db import SessionFactory
from app.modules.financial.infra.opendart import OpenDartClient
from app.modules.financial.service.collect_company_financials import collect_company_financials
from app.modules.knowledge.infra.embedding import OllamaEmbeddingProvider
from app.modules.knowledge.service.ingest_markdown import ingest_markdown


def stock_code(value: str) -> str:
    if len(value) != 6 or not value.isdigit():
        raise argparse.ArgumentTypeError("code must be exactly 6 digits")
    return value


def business_year(value: str) -> int:
    year = int(value)
    if not 2015 <= year <= date.today().year:
        raise argparse.ArgumentTypeError(f"year must be between 2015 and {date.today().year}")
    return year


async def run(code: str, year: int, dry_run: bool) -> int:
    settings = get_settings()
    if not settings.opendart.api_key:
        print("error: OPENDART__API_KEY is required")
        return 2

    try:
        async with OpenDartClient(
            api_key=settings.opendart.api_key,
            base_url=str(settings.opendart.base_url),
            timeout_seconds=settings.opendart.timeout_seconds,
        ) as client:
            if dry_run:
                summary = await collect_company_financials(
                    client=client,
                    stock_code=code,
                    business_year=year,
                    raw_dir=settings.opendart.raw_dir,
                    markdown_dir=settings.opendart.markdown_dir,
                    dry_run=True,
                )
            else:
                async with OllamaEmbeddingProvider(
                    model=settings.embedding.model,
                    dimensions=settings.embedding.dimensions,
                    base_url=str(settings.embedding.base_url),
                    timeout_seconds=settings.embedding.timeout_seconds,
                ) as provider:

                    async def ingest(path: Path) -> str:
                        async with SessionFactory() as session:
                            return (await ingest_markdown(path, session, provider)).value

                    summary = await collect_company_financials(
                        client=client,
                        stock_code=code,
                        business_year=year,
                        raw_dir=settings.opendart.raw_dir,
                        markdown_dir=settings.opendart.markdown_dir,
                        ingest=ingest,
                    )
    except Exception as exc:
        print(f"error: {exc}")
        return 1

    counts = summary.counts
    print(f"company: {summary.company_name} ({summary.stock_code}), year={summary.business_year}")
    print(
        "summary: "
        f"created={counts.get('created', 0)} "
        f"updated={counts.get('updated', 0)} "
        f"unchanged={counts.get('unchanged', 0)} "
        f"no_data={counts.get('no_data', 0)} "
        f"failed={counts.get('failed', 0)}"
    )
    return 1 if summary.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect OpenDART financial reports.")
    parser.add_argument("--code", required=True, type=stock_code)
    parser.add_argument("--year", type=business_year, default=date.today().year)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    return asyncio.run(run(arguments.code, arguments.year, arguments.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
