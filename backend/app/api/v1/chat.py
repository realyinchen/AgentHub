"""Chat conversation endpoints — streaming, invocation, and history.

Routes:
    POST /chat/stream                   — SSE streaming agent response
    POST /chat/invoke                   — Async invoke (one-shot) agent response
    GET  /chat/history/{thread_id}      — Conversation history + step sequence
"""

import asyncio
import logging
from uuid import UUID
from typing import Any

from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.api.v1.stream import streaming_message_generator
from app.schemas.chat import (
    ChatMessage,
    ConversationInfoResponse,
    UserInput,
    ChatHistory,
)
from app.schemas.trace import StepOutput
from app.agents import get_supervisor
from app.crud import chat as chat_crud
from app.crud import trace as trace_crud
from app.infra.config import get_settings
from app.infra.llm.model_manager import get_model_manager
from app.utils.request_handler import build_agent_kwargs
from app.utils.message_utils import (
    langchain_to_chat_message,
    collect_tool_calls_for_final_response,
)
from app.utils.stream_helpers import resolve_model_name, persist_tokens_and_dag
from app.utils.token_utils import extract_usage, accumulate_usage, empty_totals


logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/chat", tags=["Chat"])


def _sse_response_example() -> dict[int | str, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }


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
    return StreamingResponse(
        streaming_message_generator(user_input, supervisor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    timeout = settings.AGENT_INVOKE_TIMEOUT if settings.AGENT_INVOKE_TIMEOUT > 0 else None
    try:
        async with asyncio.timeout(timeout):
            response_events: list[tuple[str, Any]] = await supervisor.ainvoke(
                **kwargs,
                stream_mode=["updates", "values"],
            )
    except asyncio.TimeoutError:
        logger.error(
            "Agent invocation timed out after %.0fs: thread_id=%s",
            timeout,
            user_input.thread_id,
        )
        raise HTTPException(
            status_code=504,
            detail=f"Agent invocation timed out after {timeout:.0f}s. Please try again with a simpler query.",
        )
    if not response_events:
        raise HTTPException(
            status_code=500,
            detail="Agent invocation returned no events",
        )
    response_type, response = response_events[-1]

    # ── Stage 0 T03: Log structured routing decision when available ─
    structured_response = response.get("structured_response") if isinstance(response, dict) else None
    if structured_response is not None:
        logger.info(
            "Structured routing decision: action=%s target_agent=%s reasoning=%s",
            getattr(structured_response, "action", structured_response.get("action")),
            getattr(structured_response, "target_agent", structured_response.get("target_agent")),
            getattr(structured_response, "reasoning", structured_response.get("reasoning"))[:200],
        )

    if response_type == "values":
        output = langchain_to_chat_message(response["messages"][-1])
    elif response_type == "updates" and "__interrupt__" in response:
        output = langchain_to_chat_message(
            AIMessage(content=response["__interrupt__"][0].value)
        )
    else:
        raise ValueError(f"Unexpected response type: {response_type}")

    # ── Accumulate token usage from all AI messages ─────────────────
    totals = empty_totals()
    for event_type, event in response_events:
        if event_type == "values" and isinstance(event, dict):
            messages = event.get("messages", [])
            for msg in messages:
                if isinstance(msg, AIMessage):
                    usage = extract_usage(msg)
                    if usage:
                        accumulate_usage(totals, usage)

    # ── Unified token + DAG persistence (shared with stream) ────────
    await persist_tokens_and_dag(
        db=db,
        agent=supervisor,
        thread_id=user_input.thread_id,
        request_id=user_input.request_id,
        model_name=initial_model,
        tokens=totals,
    )

    return output


@api_router.get("/history/{thread_id}")
async def history(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChatHistory:
    """Get chat history with message sequence for sidebar."""
    if not thread_id:
        return ChatHistory(messages=[], message_sequence=[])

    supervisor = get_supervisor()

    # Get message steps from persisted DAG for sidebar (no graph needed)
    _, steps, _ = await trace_crud.get_latest_dag_and_steps(db, thread_id)
    message_sequence: list[StepOutput] = [StepOutput(**s) for s in (steps or [])]

    # Get messages from checkpointer for main chat UI
    config = RunnableConfig({"configurable": {"thread_id": thread_id}})
    state_snapshot = await supervisor.aget_state(config=config)
    messages: list[AnyMessage] = state_snapshot.values.get("messages", [])

    # Build messages for main chat UI: only human and final AI messages
    chat_messages: list[ChatMessage] = []

    for i, msg in enumerate(messages):
        # Skip ToolMessage - not shown in main chat
        if isinstance(msg, ToolMessage):
            continue

        # For AIMessage: only include if it has content and no tool_calls
        if isinstance(msg, AIMessage):
            if msg.tool_calls:
                continue
            if not msg.content or not str(msg.content).strip():
                continue

        chat_message = langchain_to_chat_message(msg)

        # For final AI messages, collect tool info from preceding messages
        if isinstance(msg, AIMessage) and msg.content and str(msg.content).strip():
            tool_info = collect_tool_calls_for_final_response(messages, i)
            if tool_info:
                chat_message.custom_data["tool_info"] = tool_info

        chat_messages.append(chat_message)

    return ChatHistory(messages=chat_messages, message_sequence=message_sequence)


@api_router.get(
    "/conversation-info/{thread_id}", response_model=ConversationInfoResponse
)
async def get_conversation_info(
    thread_id: UUID,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> ConversationInfoResponse:
    """Get the last-used model for a conversation.

    Used when entering a historical conversation. Returns the model_name
    from the most recent trace execution. If the model is no longer
    active, falls back to the system default.
    """
    try:
        # Verify the conversation belongs to the user
        conv = await chat_crud.read_conversation_by_thread_id(
            db=db, thread_id=thread_id, user_id=user_id
        )
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        model_name = await chat_crud.get_latest_model_name(db, thread_id)

        # Validate model is still active
        model_fallback = False
        if model_name:
            manager = get_model_manager()
            if not manager.is_model_active(model_name):
                model_name = (
                    manager.get_default_llm_id() or manager.get_first_active_llm_id()
                )
                model_fallback = True
        else:
            manager = get_model_manager()
            model_name = (
                manager.get_default_llm_id() or manager.get_first_active_llm_id()
            )

        return ConversationInfoResponse(
            model_name=model_name,
            model_fallback=model_fallback,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting conversation info for thread %s: %s", thread_id, e)
        raise HTTPException(
            status_code=500, detail="Error retrieving conversation info"
        )