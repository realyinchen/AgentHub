"""Chat conversation endpoints — streaming, invocation, and history.

Routes:
    POST /chat/stream                          — SSE streaming agent response
    POST /chat/invoke                          — Async invoke (one-shot) agent response
    GET  /chat/history/{agent_id}/{thread_id}  — Conversation history + step sequence
"""

import logging
from uuid import UUID
from typing import Any

from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.api.v1.stream import streaming_message_generator
from app.schemas.chat import (
    ChatMessage,
    UserInput,
    ChatHistory,
)
from app.schemas.trace import StepOutput
from app.agents.registry import get_graph
from app.observability import TraceBuilder
from app.utils.request_handler import build_agent_kwargs
from app.utils.message_utils import (
    langchain_to_chat_message,
    collect_tool_calls_for_final_response,
)


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
    """Stream an agent's response to a user input, including intermediate messages and tokens."""
    agent_id = user_input.agent_id
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    logger.info(
        "stream endpoint called: agent_id=%s, thread_id=%s, thinking_mode=%s",
        agent_id,
        user_input.thread_id,
        user_input.thinking_mode,
    )

    agent = get_graph(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=400, detail=f"Agent '{agent_id}' not found or not active"
        )
    return StreamingResponse(
        streaming_message_generator(user_input, agent),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@api_router.post("/invoke")
async def invoke(user_input: UserInput) -> ChatMessage:
    """Async invoke an agent with user input to retrieve a final response."""
    agent_id = user_input.agent_id
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    agent = get_graph(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=400, detail=f"Agent '{agent_id}' not found or not active"
        )
    kwargs = await build_agent_kwargs(user_input)

    response_events: list[tuple[str, Any]] = await agent.ainvoke(
        **kwargs,
        stream_mode=["updates", "values"],
    )
    response_type, response = response_events[-1]
    if response_type == "values":
        output = langchain_to_chat_message(response["messages"][-1])
    elif response_type == "updates" and "__interrupt__" in response:
        output = langchain_to_chat_message(
            AIMessage(content=response["__interrupt__"][0].value)
        )
    else:
        raise ValueError(f"Unexpected response type: {response_type}")

    return output


@api_router.get("/history/{agent_id}/{thread_id}")
async def history(
    agent_id: str,
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChatHistory:
    """Get chat history with message sequence for sidebar."""
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    if not thread_id:
        return ChatHistory(messages=[], message_sequence=[])

    # Get message steps from checkpointer for sidebar
    agent = get_graph(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"Agent '{agent_id}' not found or not active"
        )
    trace_reader = TraceBuilder(agent)
    all_steps = await trace_reader.get_execution_trace(str(thread_id))

    # Build message_sequence for sidebar
    message_sequence: list[StepOutput] = []
    for step in all_steps:
        # Only include steps that have visible messages (not metadata-only checkpoints)
        if hasattr(step, "message_type") or hasattr(step, "message_id"):
            message_sequence.append(step)

    # Get messages from checkpointer for main chat UI
    config = RunnableConfig({"configurable": {"thread_id": thread_id}})
    state_snapshot = await agent.aget_state(config=config)
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
