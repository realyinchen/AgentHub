"""Generic memory tools for the supervisor agent."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.services.memory import get_memory_orchestrator
from app.services.tool_admission import (
    ToolAdmissionResult,
    ToolPolicyDeclaration,
    get_tool_admission_gate,
)


SEARCH_MEMORY_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="search_memory",
    required_policy_flags=["can_search_memory"],
    side_effect_scope="memory_read",
    blocked_status="tool_blocked",
)
FORGET_MEMORY_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="forget_memory",
    required_policy_flags=["can_manage_memory"],
    side_effect_scope="long_term_memory",
    writes_long_term_memory=True,
    blocked_status="tool_blocked",
)


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
        description=(
            "user for profile facts, habits, routines, and identity; or book, "
            "author, tag, theme, style, genre, mood, pacing, or content."
        )
    )
    value: str = Field(description="Concise memory value to persist.")
    polarity: str = Field(
        default="neutral",
        description="like, dislike, neutral, want, read, or avoid.",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    thread_id: UUID | None = None
    source: str = Field(default="chat_turn")
    scope: str = Field(default="long_term_memory")
    source_text: str = Field(default="")
    source_kind: str = Field(default="user_message")
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


def _tool_blocked_payload(
    admission: ToolAdmissionResult,
    *,
    extra: dict[str, Any] | None = None,
) -> str:
    payload = {
        "status": admission.blocked_status or "tool_blocked",
        "tool_name": admission.tool_name,
        "tool_admission": admission.model_dump(mode="json"),
    }
    payload.update(extra or {})
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=SearchMemoryInput)
async def search_memory(
    user_id: UUID,
    query: str = "",
    thread_id: UUID | None = None,
    memory_types: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Search the user's active long-term memory."""
    admission = get_tool_admission_gate().admit_current_turn(SEARCH_MEMORY_TOOL_POLICY)
    if not admission.allowed:
        return _tool_blocked_payload(
            admission,
            extra={
                "profile_summary": "",
                "preferred_tags": [],
                "disliked_tags": [],
                "favorite_authors": [],
                "disliked_authors": [],
                "reading_states": [],
                "relevant_events": [],
                "provider_sources": [],
                "provider_telemetry": [],
            },
        )
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
    scope: str = "long_term_memory",
    source_text: str = "",
    source_kind: str = "user_message",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Retired agent write tool; chat facts must use the pre-commit pipeline."""
    del (
        user_id,
        type,
        subject,
        value,
        polarity,
        confidence,
        thread_id,
        source,
        scope,
        source_text,
        source_kind,
        metadata,
    )
    return json.dumps(
        {
            "status": "tool_blocked",
            "tool_name": "remember_memory",
            "reason": "precommit_pipeline_required",
            "memory": None,
        },
        ensure_ascii=False,
    )


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
    """Retired agent write tool; corrections use the pre-commit pipeline."""
    del (
        user_id,
        new_subject,
        new_value,
        memory_id,
        old_value,
        old_subject,
        old_type,
        new_type,
        new_polarity,
        confidence,
        thread_id,
        source,
        metadata,
    )
    return json.dumps(
        {
            "status": "tool_blocked",
            "tool_name": "revise_memory",
            "reason": "precommit_pipeline_required",
            "memory": None,
        },
        ensure_ascii=False,
    )


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
    admission = get_tool_admission_gate().admit_current_turn(FORGET_MEMORY_TOOL_POLICY)
    if not admission.allowed:
        return _tool_blocked_payload(
            admission,
            extra={
                "forgotten_count": 0,
                "forgotten_event_ids": [],
                "provider_sources": [],
            },
        )
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
