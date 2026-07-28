from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import cached_property
from typing import Any
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models import Gemini
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.base_session_service import BaseSessionService
from google.genai import Client, types
from pydantic import PrivateAttr

from app.config import AdkSettings
from app.modules.agent.domain.answer import (
    POLICY_BLOCKED_ANSWER,
    AgentProtocolError,
    AgentTools,
    AgentUnavailableError,
)

AGENT_INSTRUCTION = """
당신은 사용자의 개인 Second-Brain을 조회하는 질의응답 에이전트다.
답변하기 전에 반드시 제공된 검색 도구 중 하나를 사용하여 근거를 찾는다.

규칙:
1. 검색 도구 결과에 포함되지 않은 사실, 숫자와 날짜를 추측하지 않는다.
2. 재무 질문은 query_financial_facts를 우선 사용한다.
3. 연결재무제표와 별도재무제표를 명확히 구분한다.
4. 서로 충돌하는 자료가 있으면 충돌 사실을 명시한다.
5. no_results이면 자료가 부족하다고 답한다.
6. blocked_by_policy이면 정책상 외부 답변을 만들 수 없다고 답한다.
7. 답변 마지막에 사용한 문서 제목과 출처 식별자를 표시한다.
8. 동일한 인자로 검색 도구를 불필요하게 반복 호출하지 않는다.
9. 질문 언어에 맞춰 직접적이고 간결하게 답한다.
""".strip()
MAX_LLM_CALLS_PER_TURN = 4
SESSION_CLEANUP_TIMEOUT_SECONDS = 5
logger = logging.getLogger(__name__)


class _ApiKeyGemini(Gemini):
    """Bind one explicit Google GenAI client to a Gemma model instance.
    Credentials remain instance-scoped and never mutate process environment."""

    _explicit_client: Client = PrivateAttr()

    def __init__(self, *, model: str, api_key: str) -> None:
        """Create the model and its credential-bound Google GenAI client."""
        super().__init__(model=model)
        self._explicit_client = Client(api_key=api_key)

    @cached_property
    def api_client(self) -> Client:
        """Return the instance-scoped client used for every model request."""
        return self._explicit_client

    async def aclose(self) -> None:
        """Close both async and synchronous transports owned by the client."""
        await self._explicit_client.aio.aclose()
        self._explicit_client.close()


class GoogleAdkRunner:
    """Execute grounded answer turns with Google ADK and hosted Gemma.
    A shared model client is reused while each turn gets an ephemeral ADK session."""

    def __init__(
        self,
        settings: AdkSettings,
        *,
        session_service: BaseSessionService | None = None,
    ) -> None:
        """Store validated settings and initialize process-local sessions."""
        self.settings = settings
        self.session_service = session_service or InMemorySessionService()
        self.model = (
            _create_model(model=settings.model, api_key=settings.api_key)
            if settings.api_key
            else None
        )

    async def run(
        self,
        question: str,
        conversation_id: str,
        tools: AgentTools,
    ) -> str:
        """Run one ADK turn and return its final non-empty model response.
        Provider failures are converted to redacted domain exceptions."""
        if not self.settings.api_key:
            raise AgentUnavailableError("Google ADK API key is not configured")
        if self.model is None:
            raise AgentUnavailableError("Google ADK model is not configured")
        session_id = str(uuid4())
        session_created = False
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                await self.session_service.create_session(
                    app_name=self.settings.app_name,
                    user_id=self.settings.user_id,
                    session_id=session_id,
                )
                session_created = True
                agent = LlmAgent(
                    name="second_brain_agent",
                    description="Answers questions using Second-Brain retrieval tools.",
                    model=self.model,
                    instruction=AGENT_INSTRUCTION,
                    include_contents="none",
                    before_model_callback=_policy_callback(tools),
                    tools=[
                        tools.search_knowledge,
                        tools.query_financial_facts,
                    ],
                )
                runner = Runner(
                    agent=agent,
                    app_name=self.settings.app_name,
                    session_service=self.session_service,
                )
                final_text = await _consume_final_text(
                    runner.run_async(
                        user_id=self.settings.user_id,
                        session_id=session_id,
                        new_message=types.Content(
                            role="user",
                            parts=[types.Part(text=question)],
                        ),
                        run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS_PER_TURN),
                    )
                )
            if not final_text:
                raise AgentProtocolError("Google ADK returned no final response text")
        except AgentProtocolError:
            raise
        except Exception as exc:
            raise AgentUnavailableError("Google ADK request failed") from exc
        finally:
            if session_created:
                await self._delete_session(session_id)
        return final_text

    async def _delete_session(self, session_id: str) -> None:
        """Best-effort cleanup that cannot replace the primary turn outcome."""
        try:
            async with asyncio.timeout(SESSION_CLEANUP_TIMEOUT_SECONDS):
                await self.session_service.delete_session(
                    app_name=self.settings.app_name,
                    user_id=self.settings.user_id,
                    session_id=session_id,
                )
        except Exception:
            logger.warning("Failed to delete ephemeral ADK session", exc_info=True)

    async def aclose(self) -> None:
        """Release the shared model client's HTTP transports."""
        if self.model is not None:
            await self.model.aclose()


def _policy_callback(tools: AgentTools):
    """Return a callback that skips model generation after a blocked Tool result."""

    def stop_if_blocked(
        callback_context: object,
        llm_request: object,
    ) -> LlmResponse | None:
        """Return the fixed policy response only after local-only evidence appears."""
        del callback_context, llm_request
        if not tools.blocked_by_policy:
            return None
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=POLICY_BLOCKED_ANSWER)],
            )
        )

    return stop_if_blocked


def _create_model(*, model: str, api_key: str) -> _ApiKeyGemini:
    """Create a Gemma model whose explicit client owns its API key."""
    return _ApiKeyGemini(model=model, api_key=api_key)


async def _consume_final_text(events: AsyncIterator[Any]) -> str:
    """Consume ADK events and return text from the last final response."""
    final_text = ""
    async for event in events:
        if not event.is_final_response() or event.content is None:
            continue
        parts = getattr(event.content, "parts", None) or []
        text_parts = [
            str(part.text)
            for part in parts
            if getattr(part, "text", None) is not None and str(part.text).strip()
        ]
        if text_parts:
            final_text = "".join(text_parts).strip()
    return final_text
