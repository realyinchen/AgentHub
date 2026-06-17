"""Generic memory tools for the supervisor agent."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.services.memory import MemoryEvent, get_memory_orchestrator


class SearchMemoryInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    query: str = Field(
        default="",
        description="Optional natural-language memory search query.",
    )
    thread_id: UUID | None = Field(
        default=None,
        description="Optional current conversation thread ID.",
    )
    memory_types: list[str] | None = Field(
        default=None,
        description="Optional memory types to search, e.g. preference or reading_state.",
    )
    limit: int = Field(default=10, ge=1, le=50)


class RememberMemoryInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    type: str = Field(description="preference, feedback, reading_state, or correction.")
    subject: str = Field(
        description="user, book, author, tag, theme, style, genre, mood, pacing, or content."
    )
    value: str = Field(description="Concise memory value to persist.")
    polarity: str = Field(
        default="neutral",
        description="like, dislike, neutral, want, read, or avoid.",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    thread_id: UUID | None = None
    source: str = Field(default="chat_turn")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviseMemoryInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    memory_id: UUID | None = Field(
        default=None,
        description="Known memory event ID to revise, if available.",
    )
    old_value: str = Field(
        default="",
        description="Old memory value to find when memory_id is unknown.",
    )
    old_subject: str = Field(default="", description="Old memory subject, if known.")
    old_type: str = Field(default="", description="Old memory type, if known.")
    new_type: str = Field(default="correction")
    new_subject: str = Field(description="Corrected subject.")
    new_value: str = Field(description="Corrected memory value.")
    new_polarity: str = Field(default="neutral")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    thread_id: UUID | None = None
    source: str = Field(default="chat_turn")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ForgetMemoryInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    memory_id: UUID | None = Field(
        default=None,
        description="Known memory event ID to forget, if available.",
    )
    subject: str = Field(default="", description="Memory subject filter.")
    value: str = Field(default="", description="Memory value filter.")
    memory_type: str = Field(default="", description="Memory type filter.")
    thread_id: UUID | None = None
    reason: str = Field(default="", description="Brief forgetting/correction reason.")


@tool(args_schema=SearchMemoryInput)
async def search_memory(
    user_id: UUID,
    query: str = "",
    thread_id: UUID | None = None,
    memory_types: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Search the user's active long-term reading memory."""
    result = await get_memory_orchestrator().search_memory(
        user_id=user_id,
        query=query,
        thread_id=thread_id,
        memory_types=memory_types,
        limit=limit,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=RememberMemoryInput)
async def remember_memory(
    user_id: UUID,
    type: str,
    subject: str,
    value: str,
    polarity: str = "neutral",
    confidence: float = 1.0,
    thread_id: UUID | None = None,
    source: str = "chat_turn",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Persist a new user memory event."""
    event = MemoryEvent(
        user_id=user_id,
        thread_id=thread_id,
        type=type,
        subject=subject,
        value=value,
        polarity=polarity,
        confidence=confidence,
        source=source,
        metadata=metadata or {},
    )
    saved = await get_memory_orchestrator().remember_memory(event)
    return json.dumps(saved.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=ReviseMemoryInput)
async def revise_memory(
    user_id: UUID,
    new_subject: str,
    new_value: str,
    memory_id: UUID | None = None,
    old_value: str = "",
    old_subject: str = "",
    old_type: str = "",
    new_type: str = "correction",
    new_polarity: str = "neutral",
    confidence: float = 1.0,
    thread_id: UUID | None = None,
    source: str = "chat_turn",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Revise a prior memory by superseding it with a corrected event."""
    new_event = MemoryEvent(
        user_id=user_id,
        thread_id=thread_id,
        type=new_type,
        subject=new_subject,
        value=new_value,
        polarity=new_polarity,
        confidence=confidence,
        source=source,
        metadata=metadata or {},
    )
    saved = await get_memory_orchestrator().revise_memory(
        user_id=user_id,
        new_event=new_event,
        memory_id=memory_id,
        old_value=old_value,
        old_subject=old_subject,
        old_type=old_type,
    )
    return json.dumps(saved.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=ForgetMemoryInput)
async def forget_memory(
    user_id: UUID,
    memory_id: UUID | None = None,
    subject: str = "",
    value: str = "",
    memory_type: str = "",
    thread_id: UUID | None = None,
    reason: str = "",
) -> str:
    """Forget matching user memories so they no longer affect recommendations."""
    result = await get_memory_orchestrator().forget_memory(
        user_id=user_id,
        memory_id=memory_id,
        subject=subject,
        value=value,
        memory_type=memory_type,
        thread_id=thread_id,
        reason=reason,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
