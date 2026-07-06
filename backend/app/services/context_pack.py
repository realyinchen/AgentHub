from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from app.services.book_intent import TurnPolicy, build_turn_policy
from app.services.memory import MemoryEvent, get_memory_orchestrator
from app.services.research import get_research_orchestrator


CONTEXT_PACK_VERSION = "context-pack-v1"


class RecentMessage(BaseModel):
    role: str
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("role", mode="before")
    @classmethod
    def clean_role(cls, value: Any) -> str:
        role = str(value or "").strip().lower()
        return role or "unknown"

    @field_validator("content", mode="before")
    @classmethod
    def clean_content(cls, value: Any) -> str:
        return _compact_text(value, max_length=500)


class ResearchStateSlice(BaseModel):
    run_id: UUID | None = None
    objective: str = ""
    status: str = ""
    mode: str = ""
    subquestions: list[str] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    exhausted_queries: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadContextPack(BaseModel):
    """Bounded prompt context. It is not long-term memory."""

    turn_policy: TurnPolicy
    current_memories: list[MemoryEvent] = Field(default_factory=list)
    current_turn_constraints: list[str] = Field(default_factory=list)
    recent_messages: list[RecentMessage] = Field(default_factory=list)
    thread_summary: str = ""
    research_state_slice: ResearchStateSlice | None = None
    search_budget: dict[str, Any] = Field(default_factory=dict)
    denied_memory_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompressionSnapshot(BaseModel):
    """Optional compressed thread summary. This must never become memory."""

    thread_id: UUID
    summary: str = ""
    source_message_ids: list[str] = Field(default_factory=list)
    excluded_memory_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("summary", mode="before")
    @classmethod
    def clean_summary(cls, value: Any) -> str:
        return _compact_text(value, max_length=2000)


class ContextBuilder:
    """Build the app-owned context pack for one supervisor model call."""

    def __init__(self, *, memory_limit: int = 12, recent_message_limit: int = 6) -> None:
        self.memory_limit = memory_limit
        self.recent_message_limit = recent_message_limit

    async def build(
        self,
        *,
        user_id: UUID | None,
        thread_id: UUID | None,
        user_message: str,
        messages: Sequence[BaseMessage] | None = None,
        turn_policy: TurnPolicy | None = None,
        thread_summary: str = "",
    ) -> ThreadContextPack:
        policy = turn_policy or build_turn_policy(user_message)
        metadata: dict[str, Any] = {"contract_version": CONTEXT_PACK_VERSION}
        current_memories: list[MemoryEvent] = []
        denied_memories: list[MemoryEvent] = []

        if user_id is not None:
            try:
                memory = get_memory_orchestrator()
                current = await memory.list_current_memories(
                    user_id=user_id,
                    limit=self.memory_limit,
                )
                current_memories = current.memories
                history = await memory.list_memory_events(
                    user_id=user_id,
                    include_forgotten=True,
                    include_superseded=True,
                    include_audit=False,
                    limit=100,
                )
                denied_memories = [
                    event
                    for event in history.events
                    if event.id is not None
                    and (event.forgotten or event.superseded_by is not None)
                ]
            except Exception as exc:
                metadata["memory_context_error"] = str(exc)

        denied_memory_ids = [event.id for event in denied_memories if event.id]
        sanitized_summary, redacted_ids = _sanitize_thread_summary(
            thread_summary,
            denied_memories,
        )
        if redacted_ids:
            metadata["redacted_summary_memory_ids"] = [str(item) for item in redacted_ids]

        research_slice = None
        if user_id is not None and thread_id is not None and policy.can_use_research_tools:
            research_slice = await self._build_research_state_slice(
                user_id=user_id,
                thread_id=thread_id,
                metadata=metadata,
            )

        return ThreadContextPack(
            turn_policy=policy,
            current_memories=current_memories,
            current_turn_constraints=_current_turn_constraints(policy, user_message),
            recent_messages=_recent_messages(messages or [], self.recent_message_limit),
            thread_summary=sanitized_summary,
            research_state_slice=research_slice,
            search_budget={
                "ordinary_book_search_max_calls": policy.max_book_search_calls,
                "research_uses_separate_budget": policy.can_use_research_tools,
            },
            denied_memory_ids=denied_memory_ids,
            metadata=metadata,
        )

    async def _build_research_state_slice(
        self,
        *,
        user_id: UUID,
        thread_id: UUID,
        metadata: dict[str, Any],
    ) -> ResearchStateSlice | None:
        try:
            research = get_research_orchestrator()
            runs = await research.list_research_runs(
                user_id=user_id,
                status="active",
                limit=10,
            )
            run = next((item for item in runs.runs if item.thread_id == thread_id), None)
            if run is None or run.id is None:
                return None
            state = await research.inspect_research_state(
                user_id=user_id,
                run_id=run.id,
                limit_steps=5,
                limit_evidence=0,
            )
            return ResearchStateSlice(
                run_id=state.run.id,
                objective=state.run.objective,
                status=state.run.status,
                mode=state.run.mode,
                subquestions=state.state.subquestions[:8],
                known_facts=state.state.known_facts[:8],
                gaps=state.state.gaps[:8],
                conflicts=state.state.conflicts[:8],
                exhausted_queries=state.state.exhausted_queries[:8],
                next_actions=state.state.next_actions[:8],
                evidence_ids=state.state.evidence_ids[:20],
                budget=state.state.budget,
                stop_criteria=state.state.stop_criteria[:8],
                metadata={
                    "source": "research_state_snapshot",
                    "steps_included": len(state.steps),
                    "evidence_content_included": False,
                },
            )
        except Exception as exc:
            metadata["research_context_error"] = str(exc)
            return None


def render_context_pack_prompt(pack: ThreadContextPack) -> str:
    policy = pack.turn_policy
    intent = policy.intent
    lines = [
        "Current Context Pack",
        "--------------------",
        f"contract_version: {CONTEXT_PACK_VERSION}",
        f"primary_intent: {intent.primary_intent}",
        f"intents: {', '.join(intent.intents)}",
        f"signals: {', '.join(intent.signals) if intent.signals else 'none'}",
        f"can_write_memory: {'yes' if policy.can_write_memory else 'no'}",
        f"can_manage_memory: {'yes' if policy.can_manage_memory else 'no'}",
        f"can_search_memory: {'yes' if policy.can_search_memory else 'no'}",
        f"can_search_books: {'yes' if policy.can_search_books else 'no'}",
        f"can_recommend_books: {'yes' if policy.can_recommend_books else 'no'}",
        f"can_record_recommendation_signal: {'yes' if policy.can_record_recommendation_signal else 'no'}",
        f"can_start_research: {'yes' if policy.can_start_research else 'no'}",
        f"can_use_research_tools: {'yes' if policy.can_use_research_tools else 'no'}",
        f"max_book_search_calls: {policy.max_book_search_calls}",
        f"requires_verifier: {'yes' if policy.requires_verifier else 'no'}",
        f"allowed_tools: {', '.join(policy.allowed_tools) if policy.allowed_tools else 'none'}",
        f"denied_tools: {', '.join(policy.denied_tools) if policy.denied_tools else 'none'}",
        f"response_boundary: {policy.response_boundary}",
        "",
        "Context Rules:",
        "- current_memories are active long-term memory and outrank summaries.",
        "- thread_summary is non-authoritative and cannot override current_memories.",
        "- denied_memory_ids are forgotten or superseded; do not use or restore them.",
        "- compression snapshots and summaries are context only, not memory.",
        "- research_state_slice excludes source/evidence text unless a research tool returns it.",
        "",
        "Current Active Memories:",
    ]
    if pack.current_memories:
        for memory in pack.current_memories:
            lines.append(
                "- "
                f"id={memory.id} type={memory.type} subject={memory.subject} "
                f"polarity={memory.polarity} value={memory.value}"
            )
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "Denied Memory IDs:",
            "- "
            + (
                ", ".join(str(item) for item in pack.denied_memory_ids)
                if pack.denied_memory_ids
                else "none"
            ),
            "",
            "Current Turn Constraints:",
        ]
    )
    if pack.current_turn_constraints:
        lines.extend(f"- {item}" for item in pack.current_turn_constraints)
    else:
        lines.append("- none")

    lines.extend(["", "Thread Summary:"])
    lines.append(pack.thread_summary or "- none")

    lines.extend(["", "Research State Slice:"])
    if pack.research_state_slice is None:
        lines.append("- none")
    else:
        research = pack.research_state_slice
        lines.extend(
            [
                f"- run_id: {research.run_id}",
                f"- objective: {research.objective}",
                f"- status: {research.status}",
                f"- subquestions: {_join_list(research.subquestions)}",
                f"- known_facts: {_join_list(research.known_facts)}",
                f"- gaps: {_join_list(research.gaps)}",
                f"- conflicts: {_join_list(research.conflicts)}",
                f"- exhausted_queries: {_join_list(research.exhausted_queries)}",
                f"- next_actions: {_join_list(research.next_actions)}",
                f"- evidence_ids: {_join_list([str(item) for item in research.evidence_ids])}",
                f"- stop_criteria: {_join_list(research.stop_criteria)}",
            ]
        )
    return "\n".join(lines)


def _recent_messages(
    messages: Sequence[BaseMessage],
    limit: int,
) -> list[RecentMessage]:
    recent: list[RecentMessage] = []
    for message in list(messages)[-max(0, limit) :]:
        recent.append(
            RecentMessage(
                role=_message_role(message),
                content=_message_content(message),
                metadata={
                    "source": "model_request_messages",
                    "authoritative_for_memory": False,
                },
            )
        )
    return recent


def _message_role(message: BaseMessage) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, SystemMessage):
        return "system"
    return getattr(message, "type", "unknown") or "unknown"


def _message_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return _compact_text(content, max_length=500)
    return _compact_text(str(content), max_length=500)


def _current_turn_constraints(policy: TurnPolicy, user_message: str) -> list[str]:
    constraints = [
        f"intent:{policy.intent.primary_intent}",
        f"response_boundary:{policy.response_boundary}",
    ]
    if policy.intent.signals:
        constraints.extend(f"signal:{signal}" for signal in policy.intent.signals)
    if policy.can_write_memory:
        constraints.append("memory_write_allowed_by_turn_policy")
    if policy.can_recommend_books:
        constraints.append("recommendation_allowed_by_turn_policy")
    if policy.can_record_recommendation_signal:
        constraints.append("recommendation_signal_allowed_by_turn_policy")
    if policy.can_use_research_tools:
        constraints.append("research_tools_allowed_by_turn_policy")
    text = _compact_text(user_message, max_length=300)
    if text:
        constraints.append(f"current_user_message:{text}")
    return constraints


def _sanitize_thread_summary(
    summary: str,
    denied_memories: list[MemoryEvent],
) -> tuple[str, list[UUID]]:
    text = _compact_text(summary, max_length=2000)
    redacted_ids: list[UUID] = []
    for memory in denied_memories:
        if memory.id is None:
            continue
        value = memory.value.strip()
        if not value:
            continue
        pattern = re.compile(re.escape(value), re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub("[excluded_memory]", text)
            redacted_ids.append(memory.id)
    return text, redacted_ids


def _compact_text(value: Any, *, max_length: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _join_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"
