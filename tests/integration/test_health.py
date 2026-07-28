import httpx
import pytest

from app.main import create_app
from app.modules.health.interface.controller import check_health
from app.modules.health.interface.schema import HealthResponse


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    app = create_app()

    async def healthy() -> HealthResponse:
        return HealthResponse(status="ok", database="ok", pgvector="ok")

    app.dependency_overrides[check_health] = healthy

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "pgvector": "ok"}


@pytest.mark.asyncio
async def test_health_returns_503_for_component_failure() -> None:
    app = create_app()

    async def pgvector_unavailable() -> HealthResponse:
        return HealthResponse(
            status="unavailable",
            database="ok",
            pgvector="unavailable",
        )

    app.dependency_overrides[check_health] = pgvector_unavailable

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["pgvector"] == "unavailable"


class FakeSession:
    def __init__(
        self,
        *,
        vector_enabled: bool = True,
        execute_error: Exception | None = None,
        scalar_error: Exception | None = None,
    ) -> None:
        self.vector_enabled = vector_enabled
        self.execute_error = execute_error
        self.scalar_error = scalar_error

    async def execute(self, _query: object) -> None:
        if self.execute_error is not None:
            raise self.execute_error

    async def scalar(self, _query: object) -> bool:
        if self.scalar_error is not None:
            raise self.scalar_error
        return self.vector_enabled


@pytest.mark.asyncio
async def test_check_health_returns_ok_when_dependencies_are_available() -> None:
    result = await check_health(FakeSession())  # type: ignore[arg-type]

    assert result == HealthResponse(status="ok", database="ok", pgvector="ok")


@pytest.mark.asyncio
async def test_check_health_reports_missing_pgvector() -> None:
    result = await check_health(FakeSession(vector_enabled=False))  # type: ignore[arg-type]

    assert result == HealthResponse(
        status="unavailable",
        database="ok",
        pgvector="unavailable",
    )


@pytest.mark.asyncio
async def test_check_health_reports_database_failure() -> None:
    result = await check_health(  # type: ignore[arg-type]
        FakeSession(execute_error=RuntimeError("database unavailable"))
    )

    assert result == HealthResponse(
        status="unavailable",
        database="unavailable",
        pgvector="unavailable",
    )


@pytest.mark.asyncio
async def test_check_health_keeps_database_ok_when_pgvector_probe_fails() -> None:
    result = await check_health(  # type: ignore[arg-type]
        FakeSession(scalar_error=RuntimeError("permission denied"))
    )

    assert result == HealthResponse(
        status="unavailable",
        database="ok",
        pgvector="unavailable",
    )
