from __future__ import annotations

import io
import zipfile
from datetime import date
from json import JSONDecodeError
from typing import Any
from xml.etree import ElementTree

import httpx

from app.modules.financial.domain.financial import (
    Company,
    Disclosure,
    FinancialStatement,
    ReportType,
    StatementType,
)


class OpenDartError(RuntimeError):
    """Represent an invalid transport, payload, or API status from OpenDART.
    The adapter converts external failure details into this application error."""


class OpenDartNoData(OpenDartError):
    """Represent OpenDART's valid no-data response for a required lookup.
    Callers may handle this narrower condition without hiding other API failures."""


class OpenDartClient:
    """Adapt asynchronous OpenDART endpoints into financial domain values.
    The client validates remote payloads and owns only transports it creates."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure authentication, endpoint resolution, and HTTP ownership.
        An injected client remains the caller's responsibility for testability."""
        if not api_key:
            raise ValueError("OPENDART__API_KEY is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def __aenter__(self) -> OpenDartClient:
        """Enter the asynchronous client context without extra allocation.
        The existing adapter instance is returned for request operations."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Leave the asynchronous context and release owned HTTP resources.
        Exception details are accepted but never suppressed."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client only when this adapter created it.
        Injected transports remain reusable by their external owner."""
        if self._owns_client:
            await self._client.aclose()

    async def _get_json(self, endpoint: str, **params: str) -> dict[str, Any]:
        """Request one authenticated JSON endpoint and require an object payload.
        Transport and decoding failures are normalized as ``OpenDartError``."""
        try:
            response = await self._client.get(
                f"{self._base_url}/{endpoint}",
                params={"crtfc_key": self._api_key, **params},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, JSONDecodeError, ValueError) as exc:
            raise OpenDartError(f"{endpoint}: invalid OpenDART response") from exc
        if not isinstance(payload, dict):
            raise OpenDartError(f"{endpoint}: response must be an object")
        return payload

    @staticmethod
    def _require_success(endpoint: str, payload: dict[str, Any]) -> None:
        """Validate the status fields embedded in an OpenDART response.
        No-data status receives a distinct error while all other failures are generic."""
        status = str(payload.get("status", ""))
        if status == "000":
            return
        message = str(payload.get("message", "unknown error"))
        if status == "013":
            raise OpenDartNoData(f"{endpoint}: {message}")
        raise OpenDartError(f"{endpoint}: status={status or 'missing'} message={message}")

    async def find_company(self, stock_code: str) -> Company:
        """Resolve a stock code from the zipped OpenDART corporation registry.
        The matching XML item is normalized into an immutable company value."""
        try:
            response = await self._client.get(
                f"{self._base_url}/corpCode.xml",
                params={"crtfc_key": self._api_key},
            )
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = archive.namelist()
                xml_name = next((name for name in names if name.lower().endswith(".xml")), None)
                if xml_name is None:
                    raise OpenDartError("corpCode.xml: ZIP contains no XML")
                root = ElementTree.fromstring(archive.read(xml_name))
        except OpenDartError:
            raise
        except (httpx.HTTPError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise OpenDartError("corpCode.xml: invalid OpenDART response") from exc

        for item in root.findall(".//list"):
            raw = {child.tag: child.text or "" for child in item}
            if raw.get("stock_code", "").strip() == stock_code:
                return Company(
                    corp_code=raw["corp_code"].strip(),
                    stock_code=stock_code,
                    corp_name=raw["corp_name"].strip(),
                    corp_eng_name=raw.get("corp_eng_name", "").strip(),
                    modify_date=raw.get("modify_date", "").strip(),
                    raw=raw,
                )
        raise OpenDartNoData(f"corpCode.xml: stock code {stock_code} was not found")

    async def get_company(self, corp_code: str) -> dict[str, Any]:
        """Fetch the raw OpenDART company profile for a corporation code.
        Embedded API status is validated before the payload is returned."""
        payload = await self._get_json("company.json", corp_code=corp_code)
        self._require_success("company.json", payload)
        return payload

    async def list_disclosures(self, company: Company, year: int) -> list[Disclosure]:
        """List the company's latest periodic disclosures for a business year.
        Raw rows are normalized while a valid no-data response becomes an empty list."""
        today = date.today()
        end_date = min(date(year + 1, 12, 31), today)
        payload = await self._get_json(
            "list.json",
            corp_code=company.corp_code,
            bgn_de=f"{year}0101",
            end_de=end_date.strftime("%Y%m%d"),
            last_reprt_at="Y",
            pblntf_ty="A",
            sort="date",
            sort_mth="desc",
            page_count="100",
        )
        try:
            self._require_success("list.json", payload)
        except OpenDartNoData:
            return []
        rows = payload.get("list")
        if not isinstance(rows, list):
            raise OpenDartError("list.json: list field must be an array")
        try:
            return [
                Disclosure(
                    receipt_number=str(row["rcept_no"]),
                    report_name=str(row["report_nm"]),
                    filed_at=date.fromisoformat(
                        f"{str(row['rcept_dt'])[:4]}-{str(row['rcept_dt'])[4:6]}-"
                        f"{str(row['rcept_dt'])[6:8]}"
                    ),
                    raw=dict(row),
                )
                for row in rows
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise OpenDartError("list.json: invalid disclosure item") from exc

    async def get_statement(
        self,
        company: Company,
        year: int,
        report_type: ReportType,
        statement_type: StatementType,
    ) -> FinancialStatement | None:
        """Fetch one report and statement scope as a domain statement.
        Valid no-data responses return ``None`` while malformed payloads still fail."""
        payload = await self._get_json(
            "fnlttSinglAcntAll.json",
            corp_code=company.corp_code,
            bsns_year=str(year),
            reprt_code=report_type.code,
            fs_div=statement_type.value,
        )
        try:
            self._require_success("fnlttSinglAcntAll.json", payload)
        except OpenDartNoData:
            return None
        rows = payload.get("list")
        if not isinstance(rows, list) or not rows:
            raise OpenDartError("fnlttSinglAcntAll.json: list field must be a non-empty array")
        receipt_number = str(rows[0].get("rcept_no", ""))
        if not receipt_number:
            raise OpenDartError("fnlttSinglAcntAll.json: receipt number is missing")
        return FinancialStatement(
            report_code=report_type.code,
            statement_type=statement_type,
            receipt_number=receipt_number,
            rows=tuple(dict(row) for row in rows),
            raw=payload,
        )
