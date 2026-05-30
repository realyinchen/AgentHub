"""Agent run endpoints — invoke and streaming.

Routes:
    POST /chat/invoke  — One-shot (non-streaming) agent response
    POST /chat/stream  — SSE streaming agent response

Invoke logic is inlined directly in the endpoint handler. Streaming logic lives
in ``_streaming.py`` — a private module with the SSE projection consumers.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import get_supervisor
from app.api.v1.chat._streaming import ChatStreamingService
from app.api.v1.dependencies import get_db
from app.infra.config import get_settings
from app.schemas.agent import AgentInfo, AgentsResponse
from app.schemas.chat import ChatMessage, UserInput
from app.utils.request_handler import build_agent_kwargs
from app.utils.message_utils import langchain_to_chat_message
from app.utils.stream_helpers import (
    resolve_model_name, persist_tokens_and_dag,
    empty_totals, extract_usage, accumulate_usage,
    log_routing_decision,
)

logger = logging.getLogger(__name__)

api_router = APIRouter(tags=["Chat"])


def _sse_response_example() -> dict[int | str, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": (
                        "data: {'type': 'token', 'content': 'Hello'}\n\n"
                        "data: {'type': 'token', 'content': ' World'}\n\n"
                        "data: [DONE]\n\n"
                    ),
                    "schema": {"type": "string"},
                }
            },
        }
    }


@api_router.post("/invoke")
async def invoke(
    user_input: UserInput,
    db: AsyncSession = Depends(get_db),
) -> ChatMessage:
    """Async invoke the supervisor agent with user input to retrieve a final response.

    After the agent returns, token usage is accumulated across all AI
    messages and persisted to the conversation, and the execution DAG
    is snapshot to ``trace_executions`` for offline trace viewing.
    """
    supervisor = get_supervisor()

    # Resolve model name (shared fallback chain)
    initial_model = resolve_model_name(user_input.model_name)

    kwargs = await build_agent_kwargs(user_input)

    settings = get_settings()
    timeout = (
        settings.AGENT_INVOKE_TIMEOUT
        if settings.AGENT_INVOKE_TIMEOUT > 0
        else None
    )

    try:
        async with asyncio.timeout(timeout):
            response_events: list[tuple[str, Any]] = await supervisor.ainvoke(
                **kwargs,
                stream_mode=["updates", "values"],
            )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Agent invocation timed out after {timeout:.0f}s. "
                "Please try again with a simpler query."
            ),
        )

    if not response_events:
        raise HTTPException(status_code=500, detail="Agent invocation returned no events")

    response_type, response = response_events[-1]

    # ── Stage 0 T03: Log structured routing decision when available ─
    if isinstance(response, dict):
        log_routing_decision(response.get("structured_response"))

    # ── Parse response ────────────────────────────────────────────
    if response_type == "values":
        output = langchain_to_chat_message(response["messages"][-1])
    elif response_type == "updates" and "__interrupt__" in response:
        output = langchain_to_chat_message(
            AIMessage(content=response["__interrupt__"][0].value)
        )
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected response type: {response_type}",
        )

    # ── Accumulate token usage from all AI messages ───────────────
    totals = empty_totals()
    for event_type, event in response_events:
        if event_type == "values" and isinstance(event, dict):
            messages = event.get("messages", [])
            for msg in messages:
                if isinstance(msg, AIMessage):
                    usage = extract_usage(msg)
                    if usage:
                        accumulate_usage(totals, usage)

    # ── Unified token + DAG persistence ───────────────────────────
    await persist_tokens_and_dag(
        db=db,
        agent=supervisor,
        thread_id=user_input.thread_id,
        request_id=user_input.request_id,
        model_name=initial_model,
        tokens=totals,
    )

    return output


@api_router.post(
    "/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
)
async def stream(user_input: UserInput) -> StreamingResponse:
    """Stream the supervisor agent's response, including intermediate messages and tokens."""
    logger.info(
        "stream endpoint called: thread_id=%s, thinking_mode=%s",
        user_input.thread_id,
        user_input.thinking_mode,
    )

    supervisor = get_supervisor()
    service = ChatStreamingService(supervisor)

    return StreamingResponse(
        service.generate(user_input),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@api_router.get("/agents", response_model=AgentsResponse)
async def list_agents(
    active_only: bool = True,
    limit: int = 10,
    offset: int = 0,
) -> AgentsResponse:
    """List available agents.

    Currently returns a static list with the supervisor agent.
    This can be extended to support multiple agent types in the future.
    """
    # Currently we only have one agent (supervisor)
    # This is a static response that can be expanded later
    agents = [
        AgentInfo(
            agent_id="supervisor",
            description="Main supervisor agent that routes tasks to specialized sub-agents",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    ]

    # Filter by active status if requested
    if active_only:
        agents = [a for a in agents if a.is_active]

    # Apply pagination
    total = len(agents)
    agents = agents[offset:offset + limit]

    return AgentsResponse(agents=agents, total=total)
