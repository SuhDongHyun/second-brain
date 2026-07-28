import io
import zipfile
from datetime import date

import httpx
import pytest

from app.modules.financial.domain.financial import REPORT_TYPES, StatementType
from app.modules.financial.infra.opendart import OpenDartClient, OpenDartError


def _zip_with(name: str, content: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, content)
    return stream.getvalue()


def corp_zip() -> bytes:
    return _zip_with(
        "CORPCODE.xml",
        """<result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
<corp_eng_name>Samsung Electronics</corp_eng_name><stock_code>005930</stock_code>
<modify_date>20250101</modify_date></list></result>""",
    )


@pytest.mark.asyncio
async def test_client_maps_company_disclosures_and_statement_requests() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("corpCode.xml"):
            return httpx.Response(200, content=corp_zip())
        if request.url.path.endswith("company.json"):
            return httpx.Response(200, json={"status": "000", "corp_name": "삼성전자"})
        if request.url.path.endswith("list.json"):
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "list": [
                        {
                            "rcept_no": "20250318000984",
                            "report_nm": "사업보고서 (2024.12)",
                            "rcept_dt": "20250318",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "000",
                "list": [{"rcept_no": "20250318000984", "account_nm": "자산총계"}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OpenDartClient(
            api_key="secret", base_url="https://example.test/api", timeout_seconds=1, client=http
        )
        company = await client.find_company("005930")
        assert (await client.get_company(company.corp_code))["corp_name"] == "삼성전자"
        disclosures = await client.list_disclosures(company, 2025)
        statement = await client.get_statement(company, 2025, REPORT_TYPES[0], StatementType.CFS)

    assert company.corp_code == "00126380"
    assert disclosures[0].filed_at.isoformat() == "2025-03-18"
    assert statement is not None and statement.statement_type is StatementType.CFS
    queries = [dict(request.url.params) for request in requests]
    assert queries[2]["pblntf_ty"] == "A"
    assert queries[2]["last_reprt_at"] == "Y"
    assert queries[2]["bgn_de"] == "20250101"
    assert queries[2]["end_de"] == min(date(2026, 12, 31), date.today()).strftime("%Y%m%d")
    assert queries[3]["reprt_code"] == "11011"
    assert queries[3]["fs_div"] == "CFS"


@pytest.mark.asyncio
async def test_no_data_returns_none_and_error_hides_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        status = "013" if request.url.path.endswith("fnlttSinglAcntAll.json") else "020"
        return httpx.Response(200, json={"status": status, "message": "unavailable"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OpenDartClient(
            api_key="very-secret",
            base_url="https://example.test/api",
            timeout_seconds=1,
            client=http,
        )
        company = type("Company", (), {"corp_code": "00126380"})()
        assert await client.get_statement(company, 2025, REPORT_TYPES[0], StatementType.OFS) is None
        with pytest.raises(OpenDartError) as error:
            await client.get_company("00126380")

    assert "very-secret" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="server error"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["not", "an", "object"]),
    ],
)
async def test_json_transport_and_schema_errors_are_sanitized(response: httpx.Response) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as http:
        client = OpenDartClient(
            api_key="very-secret",
            base_url="https://example.test/api",
            timeout_seconds=1,
            client=http,
        )
        with pytest.raises(OpenDartError) as error:
            await client.get_company("00126380")

    assert "very-secret" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b"not a zip",
        (lambda: _zip_with("README.txt", "no xml"))(),
        (lambda: _zip_with("CORPCODE.xml", "<broken>"))(),
    ],
)
async def test_company_code_archive_errors_are_sanitized(content: bytes) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    ) as http:
        client = OpenDartClient(
            api_key="very-secret",
            base_url="https://example.test/api",
            timeout_seconds=1,
            client=http,
        )
        with pytest.raises(OpenDartError) as error:
            await client.find_company("005930")

    assert "very-secret" not in str(error.value)
