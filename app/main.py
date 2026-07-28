from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.composition import create_agent_runner, create_embedding_provider
from app.config import get_settings
from app.db import engine
from app.modules.health.interface.controller import router as health_router
from app.modules.knowledge.interface.controller import router as query_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    """Own application-wide embedding and database resources.
    Startup registers the provider while shutdown closes it and the engine."""
    settings = get_settings()
    provider = create_embedding_provider(settings)
    agent_runner = create_agent_runner(settings)
    application.state.embedding_provider = provider
    application.state.agent_runner = agent_runner
    application.state.adk_settings = settings.adk
    try:
        yield
    finally:
        await agent_runner.aclose()
        await provider.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    """Construct the FastAPI application and attach feature routers.
    The shared lifespan coordinates resources required by those routes."""
    application = FastAPI(title="Personal Second-Brain", lifespan=lifespan)
    application.include_router(health_router)
    application.include_router(query_router)
    return application


app = create_app()
