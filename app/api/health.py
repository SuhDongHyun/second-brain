from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]
    pgvector: Literal["ok", "unavailable"]


async def check_health(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return HealthResponse(
            status="unavailable",
            database="unavailable",
            pgvector="unavailable",
        )

    try:
        vector_enabled = bool(
            await session.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
        )
    except Exception:
        return HealthResponse(
            status="unavailable",
            database="ok",
            pgvector="unavailable",
        )

    if not vector_enabled:
        return HealthResponse(status="unavailable", database="ok", pgvector="unavailable")
    return HealthResponse(status="ok", database="ok", pgvector="ok")


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response,
    result: Annotated[HealthResponse, Depends(check_health)],
) -> HealthResponse:
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
