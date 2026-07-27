from __future__ import annotations

import ipaddress
from typing import Protocol, runtime_checkable

import httpx


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider returns an unusable response."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...

    @property
    def is_local(self) -> bool: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbeddingProvider:
    def __init__(
        self,
        *,
        model: str,
        dimensions: int,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
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
        return self._dimensions

    @property
    def is_local(self) -> bool:
        return self._is_local

    async def __aenter__(self) -> OllamaEmbeddingProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _embed(self, texts: list[str]) -> list[list[float]]:
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
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    normalized = host.lower().rstrip(".")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
