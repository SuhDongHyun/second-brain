import httpx
import pytest

from app.embeddings import EmbeddingError, OllamaEmbeddingProvider


@pytest.mark.parametrize(
    ("base_url", "is_local"),
    [
        ("http://localhost:11434", True),
        ("http://127.0.0.1:11434", True),
        ("http://[::1]:11434", True),
        ("https://ollama.example.com", False),
    ],
)
@pytest.mark.asyncio
async def test_identifies_local_endpoint(base_url: str, is_local: bool) -> None:
    provider = OllamaEmbeddingProvider(
        model="test",
        dimensions=3,
        base_url=base_url,
    )

    assert provider.is_local is is_local
    await provider.aclose()


@pytest.mark.asyncio
async def test_injected_client_is_not_trusted_as_local() -> None:
    async with httpx.AsyncClient(base_url="http://localhost:11434") as client:
        provider = OllamaEmbeddingProvider(model="test", dimensions=3, client=client)

        assert provider.is_local is False


@pytest.mark.asyncio
async def test_embed_documents_uses_current_ollama_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"embeddings": [[1, 0, 0], [0, 1, 0]]})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaEmbeddingProvider(
            model="test-model",
            dimensions=3,
            client=client,
        )
        result = await provider.embed_documents(["first", "second"])

    assert result == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert requests[0].url.path == "/api/embed"
    assert requests[0].read() == b'{"model":"test-model","input":["first","second"]}'


@pytest.mark.asyncio
async def test_empty_documents_do_not_call_http() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaEmbeddingProvider(model="test", dimensions=3, client=client)
        assert await provider.embed_documents([]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"error": "failed"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"embeddings": [[1, 2, 3]]}),
        httpx.Response(200, json={"embeddings": [[1, 2], [3, 4]]}),
    ],
)
async def test_rejects_invalid_responses(response: httpx.Response) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: response),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaEmbeddingProvider(model="test", dimensions=3, client=client)
        with pytest.raises(EmbeddingError):
            await provider.embed_documents(["first", "second"])


@pytest.mark.asyncio
async def test_embed_query_returns_single_vector() -> None:
    response = httpx.Response(200, json={"embeddings": [[1, 2, 3]]})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: response),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaEmbeddingProvider(model="test", dimensions=3, client=client)
        assert await provider.embed_query("question") == [1.0, 2.0, 3.0]
