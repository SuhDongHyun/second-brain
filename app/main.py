from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.query import router as query_router
from app.config import get_settings
from app.db import engine
from app.embeddings import OllamaEmbeddingProvider


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    provider = OllamaEmbeddingProvider(
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=str(settings.ollama_base_url),
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    application.state.embedding_provider = provider
    try:
        yield
    finally:
        await provider.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(title="Personal Second-Brain", lifespan=lifespan)
    application.include_router(health_router)
    application.include_router(query_router)
    return application


app = create_app()
