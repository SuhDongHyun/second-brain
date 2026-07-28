import argparse
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.financial.infra.opendart import OpenDartError
from app.modules.financial.service.collect_company_financials import CollectionSummary
from scripts import collect_company_info as cli
from scripts.collect_company_info import business_year, stock_code


def test_cli_validates_code_and_year() -> None:
    assert stock_code("005930") == "005930"
    assert business_year("2015") == 2015
    assert business_year(str(date.today().year)) == date.today().year

    with pytest.raises(argparse.ArgumentTypeError, match="6 digits"):
        stock_code("5930")
    with pytest.raises(argparse.ArgumentTypeError, match="between 2015"):
        business_year("2014")
    with pytest.raises((argparse.ArgumentTypeError, ValueError)):
        business_year("not-a-year")


def settings(api_key: str) -> SimpleNamespace:
    return SimpleNamespace(
        opendart=SimpleNamespace(
            api_key=api_key,
            base_url="https://example.test/api",
            timeout_seconds=1,
            raw_dir=Path("raw/opendart"),
            markdown_dir=Path("knowledge/generated/opendart"),
        ),
    )


class FakeClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_run_requires_api_key_before_constructing_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings(""))
    monkeypatch.setattr(
        cli,
        "OpenDartClient",
        lambda **kwargs: pytest.fail("client must not be constructed"),
    )

    assert await cli.run("005930", 2025, True) == 2
    assert "OPENDART__API_KEY is required" in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("counts", "expected_exit"),
    [
        ({"unchanged": 4}, 0),
        ({"unchanged": 3, "failed": 1}, 1),
    ],
)
async def test_dry_run_maps_summary_to_exit_code_without_ollama_or_db(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    counts: dict[str, int],
    expected_exit: int,
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings("very-secret"))
    monkeypatch.setattr(cli, "OpenDartClient", FakeClient)
    monkeypatch.setattr(
        cli,
        "OllamaEmbeddingProvider",
        lambda **kwargs: pytest.fail("dry-run must not construct Ollama"),
    )

    async def collect(**kwargs: object) -> CollectionSummary:
        assert kwargs["dry_run"] is True
        return CollectionSummary("삼성전자", "005930", 2025, counts)

    monkeypatch.setattr(cli, "collect_company_financials", collect)

    assert await cli.run("005930", 2025, True) == expected_exit
    output = capsys.readouterr().out
    assert "very-secret" not in output
    assert f"failed={counts.get('failed', 0)}" in output


@pytest.mark.asyncio
async def test_run_sanitizes_opendart_error_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailingClient(FakeClient):
        async def __aenter__(self) -> FakeClient:
            raise OpenDartError("company.json: invalid OpenDART response")

    monkeypatch.setattr(cli, "get_settings", lambda: settings("very-secret"))
    monkeypatch.setattr(cli, "OpenDartClient", FailingClient)

    assert await cli.run("005930", 2025, True) == 1
    output = capsys.readouterr().out
    assert "invalid OpenDART response" in output
    assert "very-secret" not in output
