"""Chat history endpoint — message history with step sequence.

Route (under parent prefix /chat):
    GET /history/{thread_id}  — Conversation history + step sequence for sidebar
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import get_agent
from app.api.v1.dependencies import get_db
from app.crud import trace as trace_crud
from app.schemas.chat import ChatHistory, ChatMessage
from app.schemas.trace import StepOutput
from app.utils.message import (
    collect_tool_calls_for_final_response,
    langchain_to_chat_message,
)

logger = logging.getLogger(__name__)

api_router = APIRouter(tags=["Chat"])


@api_router.get("/history/{thread_id}")
async def history(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChatHistory:
    """Get chat history with message sequence for sidebar."""
    if not thread_id:
        return ChatHistory(messages=[], message_sequence=[])

    supervisor = get_agent()

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
