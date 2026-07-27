from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingestion.service import IngestionResult
from scripts import ingest
from scripts.ingest import discover_markdown


def test_discover_markdown_is_recursive_and_sorted(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    second = nested / "b.md"
    first = tmp_path / "a.md"
    ignored = tmp_path / "ignored.txt"
    for path in (second, first, ignored):
        path.write_text("content", encoding="utf-8")

    assert discover_markdown([tmp_path]) == sorted([first.resolve(), second.resolve()])


def test_discover_markdown_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        discover_markdown([tmp_path / "missing"])


class AsyncContextManager:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeProvider(AsyncContextManager):
    is_local = True

    def __init__(self, **kwargs: object) -> None:
        super().__init__(self)


@pytest.mark.asyncio
async def test_run_reports_results_and_continues_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    created = tmp_path / "created.md"
    failed = tmp_path / "failed.md"
    unchanged = tmp_path / "unchanged.md"
    for path in (created, failed, unchanged):
        path.write_text("content", encoding="utf-8")

    async def fake_ingest(path: Path, session: object, provider: object) -> IngestionResult:
        if path == failed.resolve():
            raise RuntimeError("embedding unavailable")
        if path == unchanged.resolve():
            return IngestionResult.UNCHANGED
        return IngestionResult.CREATED

    monkeypatch.setattr(ingest, "SessionFactory", lambda: AsyncContextManager(object()))
    monkeypatch.setattr(ingest, "OllamaEmbeddingProvider", FakeProvider)
    monkeypatch.setattr(ingest, "ingest_markdown", fake_ingest)
    monkeypatch.setattr(
        ingest,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_model="bge-m3",
            embedding_dimensions=1024,
            ollama_base_url="http://localhost:11434",
            ollama_timeout_seconds=60,
        ),
    )

    assert await ingest.run([tmp_path]) == 1
    output = capsys.readouterr().out
    assert f"created: {created.resolve()}" in output
    assert f"failed: {failed.resolve()}: embedding unavailable" in output
    assert f"unchanged: {unchanged.resolve()}" in output
    assert "summary: created=1 updated=0 unchanged=1 failed=1" in output


@pytest.mark.asyncio
async def test_run_returns_two_for_invalid_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await ingest.run([tmp_path / "missing"]) == 2
    assert "error: path does not exist or is not Markdown" in capsys.readouterr().out
