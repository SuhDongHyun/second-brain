from __future__ import annotations

import ipaddress
from typing import Protocol, runtime_checkable

import httpx


class EmbeddingError(RuntimeError):
    """Represent a failed request or unusable response from an embedding provider.
    Infrastructure details are normalized before reaching ingestion or search services."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Define the embedding capabilities required by application services.
    Implementations expose vector shape, locality, and batch or query operations."""

    @property
    def dimensions(self) -> int:
        """Return the fixed vector size produced by the provider.
        Services use it to reject responses incompatible with storage."""
        ...

    @property
    def is_local(self) -> bool:
        """Report whether requests stay on a loopback-only provider.
        Ingestion uses this signal to enforce local-only document policy."""
        ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of document texts while preserving input order.
        One validated vector must be returned for every supplied text."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed one search query into the provider's vector space.
        The resulting vector is suitable for similarity retrieval."""
        ...


class OllamaEmbeddingProvider:
    """Adapt Ollama's embedding endpoint to the application protocol.
    Responses are validated for count, dimensions, and numeric vector values."""

    def __init__(
        self,
        *,
        model: str,
        dimensions: int,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure the Ollama model, endpoint, and HTTP client ownership.
        Locality is derived only for an internally created loopback transport."""
        self.model = model
        self._dimensions = dimensions
        self._owns_client = client is None
        endpoint = client.base_url if client is not None else httpx.URL(base_url)
        self._is_local = client is None and _is_loopback_host(endpoint.host)
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            trust_env=False,
        )

    @property
    def dimensions(self) -> int:
        """Return the configured embedding vector dimensions.
        Every provider response is checked against this value."""
        return self._dimensions

    @property
    def is_local(self) -> bool:
        """Report whether the internally managed endpoint is loopback-only.
        Injected clients are conservatively treated as non-local."""
        return self._is_local

    async def __aenter__(self) -> OllamaEmbeddingProvider:
        """Enter the asynchronous provider context using this instance.
        Resource allocation already occurred during initialization."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Exit the provider context and release owned HTTP resources.
        Exception details are accepted without suppressing the error."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close only an HTTP client created by this provider.
        Injected clients remain under the lifecycle of their caller."""
        if self._owns_client:
            await self._client.aclose()

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Send a batch to Ollama and validate its complete vector response.
        Transport, shape, and numeric failures become ``EmbeddingError``."""
        if not texts:
            return []
        try:
            response = await self._client.post(
                "/api/embed",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            data = response.json()
            embeddings = data["embeddings"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc

        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingError(
                f"Ollama returned {len(embeddings) if isinstance(embeddings, list) else 0} "
                f"embeddings for {len(texts)} inputs"
            )

        result: list[list[float]] = []
        for vector in embeddings:
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                actual = len(vector) if isinstance(vector, list) else 0
                raise EmbeddingError(
                    f"embedding dimensions mismatch: expected {self.dimensions}, got {actual}"
                )
            try:
                result.append([float(value) for value in vector])
            except (TypeError, ValueError) as exc:
                raise EmbeddingError("embedding contains a non-numeric value") from exc
        return result

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed document texts through the shared validated batch operation.
        Output order remains aligned with the original text sequence."""
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query and return its single validated vector.
        The batch implementation provides identical validation semantics."""
        return (await self._embed([text]))[0]


def _is_loopback_host(host: str | None) -> bool:
    """Determine whether a hostname or IP address resolves syntactically to loopback.
    ``localhost`` and loopback IP literals are accepted without network access."""
    if host is None:
        return False
    normalized = host.lower().rstrip(".")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
