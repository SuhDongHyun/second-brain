from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AdkSettings
from app.db import get_session
from app.modules.agent.domain.answer import (
    AgentAnswer,
    AgentProtocolError,
    AgentRunner,
    AgentUnavailableError,
    ToolTrace,
)
from app.modules.agent.service.answer_question import answer_question
from app.modules.agent.service.tools import create_retriever_tools
from app.modules.knowledge.infra.embedding import EmbeddingProvider
from app.modules.knowledge.interface.schema import AgentQueryRequest, AgentQueryResponse

router = APIRouter(prefix="/api", tags=["query"])


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    """Resolve the application-scoped embedding provider."""
    return request.app.state.embedding_provider


def get_agent_runner(request: Request) -> AgentRunner:
    """Resolve the application-scoped Google ADK runner."""
    return request.app.state.agent_runner


def get_adk_settings(request: Request) -> AdkSettings:
    """Resolve validated ADK settings stored by the application lifespan."""
    return request.app.state.adk_settings


async def execute_agent_query(
    *,
    payload: AgentQueryRequest,
    conversation_id: str,
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
    runner: AgentRunner,
    settings: AdkSettings,
) -> AgentAnswer:
    """Compose request-scoped Tools and execute the grounded answer use case."""
    trace = ToolTrace()
    tools = create_retriever_tools(
        session=session,
        embedding_provider=embedding_provider,
        request_filters=payload.filters.to_domain(),
        trace=trace,
        max_context_tokens=settings.max_context_tokens,
        max_results=settings.max_results,
    )
    return await answer_question(
        question=payload.question,
        conversation_id=conversation_id,
        runner=runner,
        tools=tools,
        trace=trace,
        model=settings.model,
    )


@router.post("/query", response_model=AgentQueryResponse)
async def query(
    payload: AgentQueryRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    runner: Annotated[AgentRunner, Depends(get_agent_runner)],
    settings: Annotated[AdkSettings, Depends(get_adk_settings)],
) -> AgentQueryResponse:
    """Generate a grounded answer and map stable failures to HTTP responses."""
    conversation_id = payload.conversation_id or str(uuid4())
    try:
        answer = await execute_agent_query(
            payload=payload,
            conversation_id=conversation_id,
            session=session,
            embedding_provider=embedding_provider,
            runner=runner,
            settings=settings,
        )
    except AgentUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="answer service unavailable",
        ) from exc
    except AgentProtocolError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="answer service returned an invalid response",
        ) from exc
    return AgentQueryResponse.from_domain(answer)
