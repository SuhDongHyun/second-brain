from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from pathlib import Path

from app.config import get_settings
from app.db import SessionFactory
from app.modules.knowledge.infra.embedding import OllamaEmbeddingProvider
from app.modules.knowledge.service.ingest_markdown import ingest_markdown


def discover_markdown(paths: list[Path]) -> list[Path]:
    discovered: set[Path] = set()
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".md":
            discovered.add(path.resolve())
        elif path.is_dir():
            discovered.update(item.resolve() for item in path.rglob("*.md") if item.is_file())
        else:
            raise FileNotFoundError(f"path does not exist or is not Markdown: {path}")
    if not discovered:
        raise FileNotFoundError("no Markdown files found")
    return sorted(discovered)


async def run(paths: list[Path]) -> int:
    try:
        files = discover_markdown(paths)
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 2

    settings = get_settings()
    counts: Counter[str] = Counter()
    async with OllamaEmbeddingProvider(
        model=settings.embedding.model,
        dimensions=settings.embedding.dimensions,
        base_url=str(settings.embedding.base_url),
        timeout_seconds=settings.embedding.timeout_seconds,
    ) as provider:
        for path in files:
            try:
                async with SessionFactory() as session:
                    result = await ingest_markdown(path, session, provider)
                counts[result.value] += 1
                print(f"{result.value}: {path}")
            except Exception as exc:
                counts["failed"] += 1
                print(f"failed: {path}: {exc}")

    print(
        "summary: "
        f"created={counts['created']} "
        f"updated={counts['updated']} "
        f"unchanged={counts['unchanged']} "
        f"failed={counts['failed']}"
    )
    return 1 if counts["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Markdown knowledge documents.")
    parser.add_argument("paths", nargs="+", type=Path)
    arguments = parser.parse_args()
    return asyncio.run(run(arguments.paths))


if __name__ == "__main__":
    raise SystemExit(main())
