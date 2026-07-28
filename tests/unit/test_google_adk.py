import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from google.adk.models.llm_response import LlmResponse

import app.modules.agent.infra.google_adk as adapter
from app.config import AdkSettings
from app.modules.agent.domain.answer import AgentProtocolError, AgentUnavailableError


class FakeSessionService:
    def __init__(self, existing: bool = False) -> None:
        self.existing = existing
        self.created: list[dict[str, str]] = []
        self.deleted: list[dict[str, str]] = []

    async def get_session(self, **_: str) -> object | None:
        return object() if self.existing else None

    async def create_session(self, **kwargs: str) -> object:
        self.created.append(kwargs)
        self.existing = True
        return object()

    async def delete_session(self, **kwargs: str) -> None:
        self.deleted.append(kwargs)
        self.existing = False


class FakeTools:
    blocked_by_policy = False

    async def search_knowledge(
        self,
        query: str,
        domain: str | None = None,
        project: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        latest: bool = False,
    ) -> dict[str, object]:
        return {"status": "ok"}

    async def query_financial_facts(
        self,
        company: str,
        metric: str | None = None,
        latest: bool = True,
        consolidated: bool = True,
    ) -> dict[str, object]:
        return {"status": "ok"}


def settings(api_key: str = "secret-key") -> AdkSettings:
    return AdkSettings(
        api_key=api_key,
        model="gemma-test",
        timeout_seconds=5,
        app_name="second_brain",
        user_id="service_user",
        max_context_tokens=6000,
        max_results=6,
    )


def event(text: str, *, final: bool = True):
    return SimpleNamespace(
        is_final_response=lambda: final,
        content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
    )


@pytest.mark.asyncio
async def test_consume_final_text_ignores_empty_events_and_joins_text_parts() -> None:
    async def events():
        yield SimpleNamespace(is_final_response=lambda: True, content=None)
        yield SimpleNamespace(
            is_final_response=lambda: True,
            content=SimpleNamespace(
                parts=[
                    SimpleNamespace(text="첫 문장"),
                    SimpleNamespace(text=None),
                    SimpleNamespace(text=" 둘째 문장 "),
                ]
            ),
        )

    assert await adapter._consume_final_text(events()) == "첫 문장 둘째 문장"


@pytest.mark.asyncio
async def test_google_adk_runner_builds_agent_tools_and_returns_final_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_model(*, model: str, api_key: str) -> object:
        captured["model"] = model
        captured["api_key"] = api_key
        return "configured-model"

    def fake_agent(**kwargs: object) -> object:
        captured["agent"] = kwargs
        return object()

    class FakeAdkRunner:
        def __init__(self, **kwargs: object) -> None:
            captured["runner"] = kwargs

        async def run_async(self, **kwargs: object):
            captured["run"] = kwargs
            yield event("중간", final=False)
            yield event("최종 답변")

    monkeypatch.setattr(adapter, "_create_model", fake_model)
    monkeypatch.setattr(adapter, "LlmAgent", fake_agent)
    monkeypatch.setattr(adapter, "Runner", FakeAdkRunner)
    session_service = FakeSessionService()
    runner = adapter.GoogleAdkRunner(settings(), session_service=session_service)  # type: ignore[arg-type]
    tools = FakeTools()

    answer = await runner.run("질문", "conversation-1", tools)

    assert answer == "최종 답변"
    assert captured["model"] == "gemma-test"
    agent_kwargs = captured["agent"]
    assert agent_kwargs["model"] == "configured-model"  # type: ignore[index]
    assert agent_kwargs["tools"] == [  # type: ignore[index]
        tools.search_knowledge,
        tools.query_financial_facts,
    ]
    assert agent_kwargs["include_contents"] == "none"  # type: ignore[index]
    instruction = str(agent_kwargs["instruction"])  # type: ignore[index]
    assert "반드시" in instruction
    assert "검색 도구" in instruction
    policy_callback = agent_kwargs["before_model_callback"]  # type: ignore[index]
    assert policy_callback(callback_context=None, llm_request=None) is None
    tools.blocked_by_policy = True
    blocked_response = policy_callback(callback_context=None, llm_request=None)
    assert isinstance(blocked_response, LlmResponse)
    assert "local_only" in blocked_response.content.parts[0].text
    assert len(session_service.created) == 1
    created_session = session_service.created[0]
    assert created_session["app_name"] == "second_brain"
    assert created_session["user_id"] == "service_user"
    assert created_session["session_id"] != "conversation-1"
    assert captured["run"]["session_id"] == created_session["session_id"]  # type: ignore[index]
    assert captured["run"]["run_config"].max_llm_calls == 4  # type: ignore[index,union-attr]
    assert session_service.deleted == [created_session]


@pytest.mark.asyncio
async def test_google_adk_runner_uses_isolated_ephemeral_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_calls = 0

    def fake_model(**_: object) -> object:
        nonlocal model_calls
        model_calls += 1
        return object()

    class FakeAdkRunner:
        def __init__(self, **_: object) -> None:
            pass

        async def run_async(self, **_: object):
            yield event("답변")

    monkeypatch.setattr(adapter, "_create_model", fake_model)
    monkeypatch.setattr(adapter, "LlmAgent", lambda **_: object())
    monkeypatch.setattr(adapter, "Runner", FakeAdkRunner)
    session_service = FakeSessionService()
    runner = adapter.GoogleAdkRunner(settings(), session_service=session_service)  # type: ignore[arg-type]

    await runner.run("첫 질문", "existing-conversation", FakeTools())
    await runner.run("둘째 질문", "existing-conversation", FakeTools())

    assert len(session_service.created) == 2
    assert session_service.created[0]["session_id"] != session_service.created[1]["session_id"]
    assert session_service.deleted == session_service.created
    assert model_calls == 1


@pytest.mark.asyncio
async def test_google_adk_runner_closes_shared_model_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeModel:
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    model = FakeModel()
    monkeypatch.setattr(adapter, "_create_model", lambda **_: model)
    runner = adapter.GoogleAdkRunner(settings())

    await runner.aclose()

    assert model.closed is True


def test_model_factory_never_mutates_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class GuardEnvironment(dict[str, str]):
        def __setitem__(self, key: str, value: str) -> None:
            raise AssertionError(f"environment mutation: {key}={value}")

        def pop(self, key: str, default: object = None) -> str | object:
            raise AssertionError(f"environment mutation: pop({key}, {default})")

    monkeypatch.setattr(
        adapter,
        "os",
        SimpleNamespace(environ=GuardEnvironment()),
        raising=False,
    )

    model = adapter._create_model(model="gemma-test", api_key="secret-key")

    assert model.model == "gemma-test"


@pytest.mark.asyncio
async def test_concurrent_model_factories_use_independent_clients() -> None:
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = await asyncio.gather(
            loop.run_in_executor(
                executor,
                lambda: adapter._create_model(model="gemma-first", api_key="first-key"),
            ),
            loop.run_in_executor(
                executor,
                lambda: adapter._create_model(model="gemma-second", api_key="second-key"),
            ),
        )

    assert first.model == "gemma-first"
    assert second.model == "gemma-second"
    assert first.api_client is not second.api_client


@pytest.mark.asyncio
async def test_google_adk_runner_requires_key_and_final_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = adapter.GoogleAdkRunner(settings(api_key=""))
    with pytest.raises(AgentUnavailableError, match="API key"):
        await runner.run("질문", "conversation-1", FakeTools())

    class EmptyRunner:
        def __init__(self, **_: object) -> None:
            pass

        async def run_async(self, **_: object):
            yield event("", final=True)

    monkeypatch.setattr(adapter, "_create_model", lambda **_: object())
    monkeypatch.setattr(adapter, "LlmAgent", lambda **_: object())
    monkeypatch.setattr(adapter, "Runner", EmptyRunner)
    with pytest.raises(AgentProtocolError, match="final response"):
        await adapter.GoogleAdkRunner(settings()).run(
            "질문",
            "conversation-1",
            FakeTools(),
        )


@pytest.mark.asyncio
async def test_google_adk_runner_redacts_external_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "super-secret-key"

    class FailingRunner:
        def __init__(self, **_: object) -> None:
            pass

        async def run_async(self, **_: object):
            if False:
                yield None
            raise RuntimeError(f"provider rejected {secret}")

    monkeypatch.setattr(adapter, "_create_model", lambda **_: object())
    monkeypatch.setattr(adapter, "LlmAgent", lambda **_: object())
    monkeypatch.setattr(adapter, "Runner", FailingRunner)

    with pytest.raises(AgentUnavailableError) as captured:
        await adapter.GoogleAdkRunner(settings(api_key=secret)).run(
            "질문",
            "conversation-1",
            FakeTools(),
        )

    assert secret not in str(captured.value)


@pytest.mark.asyncio
async def test_google_adk_runner_maps_timeout_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowRunner:
        def __init__(self, **_: object) -> None:
            pass

        async def run_async(self, **_: object):
            await asyncio.sleep(1)
            yield event("too late")

    monkeypatch.setattr(adapter, "_create_model", lambda **_: object())
    monkeypatch.setattr(adapter, "LlmAgent", lambda **_: object())
    monkeypatch.setattr(adapter, "Runner", SlowRunner)
    timeout_settings = settings()
    timeout_settings.timeout_seconds = 0.01

    with pytest.raises(AgentUnavailableError, match="request failed"):
        await adapter.GoogleAdkRunner(timeout_settings).run(
            "질문",
            "conversation-1",
            FakeTools(),
        )


@pytest.mark.asyncio
async def test_google_adk_runner_preserves_answer_when_session_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingCleanupSessionService(FakeSessionService):
        async def delete_session(self, **kwargs: str) -> None:
            raise RuntimeError(f"cleanup failed for {kwargs['session_id']}")

    class FakeAdkRunner:
        def __init__(self, **_: object) -> None:
            pass

        async def run_async(self, **_: object):
            yield event("근거 기반 답변")

    monkeypatch.setattr(adapter, "_create_model", lambda **_: object())
    monkeypatch.setattr(adapter, "LlmAgent", lambda **_: object())
    monkeypatch.setattr(adapter, "Runner", FakeAdkRunner)
    runner = adapter.GoogleAdkRunner(
        settings(),
        session_service=FailingCleanupSessionService(),  # type: ignore[arg-type]
    )

    answer = await runner.run("질문", "conversation-1", FakeTools())

    assert answer == "근거 기반 답변"
    assert "Failed to delete ephemeral ADK session" in caplog.text
