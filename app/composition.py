from app.config import Settings
from app.modules.agent.infra.google_adk import GoogleAdkRunner
from app.modules.knowledge.infra.embedding import OllamaEmbeddingProvider


def create_embedding_provider(settings: Settings) -> OllamaEmbeddingProvider:
    """Build the embedding adapter from validated application settings.
    The caller owns the returned provider's asynchronous lifecycle."""
    return OllamaEmbeddingProvider(
        model=settings.embedding.model,
        dimensions=settings.embedding.dimensions,
        base_url=str(settings.embedding.base_url),
        timeout_seconds=settings.embedding.timeout_seconds,
    )


def create_agent_runner(settings: Settings) -> GoogleAdkRunner:
    """Build the Google ADK adapter without requiring a key at startup.
    The adapter validates credentials only when the answer endpoint is invoked."""
    return GoogleAdkRunner(settings.adk)
