from __future__ import annotations

from uuid import UUID

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import get_agent
from app.crud import trace as trace_crud
from app.schemas.chat import ChatMessage
from app.utils.message import (
    collect_tool_calls_for_final_response,
    langchain_to_chat_message,
)


async def read_legacy_checkpointer_history(
    db: AsyncSession,
    *,
    thread_id: UUID,
) -> list[ChatMessage]:
    """Read and project old Checkpointer state without writing or backfilling."""

    traces = await trace_crud.get_traces_by_thread(db, thread_id)
    trace_index = 0
    config = RunnableConfig({"configurable": {"thread_id": thread_id}})
    snapshot = await get_agent().aget_state(config=config)
    messages: list[AnyMessage] = snapshot.values.get("messages", [])
    projected: list[ChatMessage] = []

    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage):
            continue
        if isinstance(message, AIMessage):
            if message.tool_calls:
                continue
            if not message.content or not str(message.content).strip():
                continue

        chat_message = langchain_to_chat_message(message)
        if (
            isinstance(message, AIMessage)
            and message.content
            and str(message.content).strip()
        ):
            tool_info = collect_tool_calls_for_final_response(
                messages,
                index,
            )
            if tool_info:
                chat_message.custom_data["tool_info"] = tool_info
            if trace_index < len(traces):
                chat_message.request_id = traces[trace_index][0]
                trace_index += 1
        projected.append(chat_message)
    return projected


__all__ = ["read_legacy_checkpointer_history"]
