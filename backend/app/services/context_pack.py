from __future__ import annotations

import re
import json
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from app.services.book_intent import TurnPolicy, build_turn_policy
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt
from app.services.memory import MemoryEvent


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
    runtime_receipt: dict[str, Any] = Field(default_factory=dict)
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
    """Purely project a bounded prompt pack from an executed plan receipt.

    This builder performs no memory, research, provider, or database reads.
    Every external fact in the pack must have arrived through SystemRuntime and
    therefore has a visible ActionReceipt.
    """

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
        action_plan: ActionPlan | dict[str, Any] | None = None,
        thread_summary: str = "",
        plan_receipt: PlanReceipt | dict[str, Any] | None = None,
    ) -> ThreadContextPack:
        plan_payload = _action_plan_payload(action_plan)
        policy, policy_source = resolve_turn_policy(
            user_message=user_message,
            action_plan=plan_payload,
            turn_policy=turn_policy,
        )
        routing_decision = _embedded_routing_decision(plan_payload)
        receipt_payload = _receipt_payload(plan_receipt)
        metadata: dict[str, Any] = {
            "contract_version": CONTEXT_PACK_VERSION,
            "source": "plan_receipt_projection",
            "policy_source": policy_source,
            "routing_policy_authoritative": policy_source.startswith("action_plan."),
            "hidden_memory_reads": False,
            "hidden_research_reads": False,
            "plan_id": receipt_payload.get("plan_id"),
        }
        if routing_decision:
            metadata["routing_decision_contract_version"] = routing_decision.get(
                "contract_version"
            )
            metadata["routing_decision_primary_intent"] = routing_decision.get(
                "primary_intent"
            )
        current_memories = _memory_events_from_receipt(
            receipt_payload,
            limit=self.memory_limit,
        )
        denied_memories = _denied_memories_from_receipt(receipt_payload)

        denied_memory_ids = [event.id for event in denied_memories if event.id]
        sanitized_summary, redacted_ids = _sanitize_thread_summary(
            thread_summary,
            denied_memories,
        )
        if redacted_ids:
            metadata["redacted_summary_memory_ids"] = [str(item) for item in redacted_ids]

        research_slice = _research_state_from_receipt(receipt_payload)

        return ThreadContextPack(
            turn_policy=policy,
            current_memories=current_memories,
            current_turn_constraints=_current_turn_constraints(
                policy,
                user_message,
                routing_decision=routing_decision,
            ),
            recent_messages=_recent_messages(messages or [], self.recent_message_limit),
            thread_summary=sanitized_summary,
            research_state_slice=research_slice,
            search_budget={
                "ordinary_book_search_max_calls": policy.max_book_search_calls,
                "research_uses_separate_budget": policy.can_use_research_tools,
            },
            denied_memory_ids=denied_memory_ids,
            runtime_receipt=receipt_payload,
            metadata=metadata,
        )


def resolve_turn_policy(
    *,
    user_message: str,
    action_plan: ActionPlan | dict[str, Any] | None = None,
    turn_policy: TurnPolicy | None = None,
) -> tuple[TurnPolicy, str]:
    """Resolve final-answer policy without reclassifying an already-routed turn.

    ActionPlan is the authoritative projection of RoutingDecision. When it
    exists, only its compiled policy (or its embedded RoutingDecision policy)
    may define the prompt policy. Explicit ``turn_policy`` and raw-text
    classification are compatibility paths for callers that have no plan.
    """

    plan_payload = _action_plan_payload(action_plan)
    if plan_payload:
        direct_policy = plan_payload.get("policy")
        if direct_policy:
            return (
                _validate_authoritative_policy(
                    direct_policy,
                    source="action_plan.policy",
                ),
                "action_plan.policy",
            )

        routing_policy = _embedded_routing_policy(plan_payload)
        if routing_policy:
            return (
                _validate_authoritative_policy(
                    routing_policy,
                    source="action_plan.routing_decision.policy",
                ),
                "action_plan.routing_decision.policy",
            )

        raise ValueError(
            "ActionPlan is present but contains no compiled routing policy; "
            "refusing to reclassify the raw user message"
        )

    if turn_policy is not None:
        return turn_policy, "provided_turn_policy"
    return build_turn_policy(user_message), "legacy_raw_text_fallback"


def render_context_pack_prompt(pack: ThreadContextPack) -> str:
    policy = pack.turn_policy
    intent = policy.intent
    lines = [
        "Current Context Pack",
        "--------------------",
        f"contract_version: {CONTEXT_PACK_VERSION}",
        f"policy_source: {pack.metadata.get('policy_source') or 'unknown'}",
        "routing_policy_authoritative: "
        + (
            "yes"
            if pack.metadata.get("routing_policy_authoritative")
            else "no"
        ),
        f"primary_intent: {intent.primary_intent}",
        f"intents: {', '.join(intent.intents)}",
        f"signals: {', '.join(intent.signals) if intent.signals else 'none'}",
        f"can_write_memory: {'yes' if policy.can_write_memory else 'no'}",
        f"can_manage_memory: {'yes' if policy.can_manage_memory else 'no'}",
        f"can_search_memory: {'yes' if policy.can_search_memory else 'no'}",
        f"can_search_books: {'yes' if policy.can_search_books else 'no'}",
        f"can_recommend_books: {'yes' if policy.can_recommend_books else 'no'}",
        f"can_view_recommendation_history: {'yes' if policy.can_view_recommendation_history else 'no'}",
        f"can_record_recommendation_signal: {'yes' if policy.can_record_recommendation_signal else 'no'}",
        f"can_start_research: {'yes' if policy.can_start_research else 'no'}",
        f"can_use_research_tools: {'yes' if policy.can_use_research_tools else 'no'}",
        f"can_use_web_search: {'yes' if policy.can_use_web_search else 'no'}",
        f"max_book_search_calls: {policy.max_book_search_calls}",
        f"requires_verifier: {'yes' if policy.requires_verifier else 'no'}",
        f"allowed_tools: {', '.join(policy.allowed_tools) if policy.allowed_tools else 'none'}",
        f"denied_tools: {', '.join(policy.denied_tools) if policy.denied_tools else 'none'}",
        f"response_boundary: {policy.response_boundary}",
        "",
        "Context Rules:",
        "- turn_policy is authoritative for this response when projected from ActionPlan.",
        "- Never infer a replacement capability policy from raw text or recent messages.",
        "- ContextPack is a projection of the current PlanReceipt; it never reads stores directly.",
        "- current_memories are user-state records returned by an executed memory action.",
        "- raw_text is the user's authoritative wording; organized fields are an interpretation.",
        "- only committed active facts are recallable as long-term memory.",
        "- unresolved or clarification-required proposals are thread workflow state, never memory evidence.",
        "- short_term records are usable only until valid_until.",
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
                f"id={memory.id} status={memory.state_status} "
                f"category={memory.state_category or 'unclassified'} "
                f"key={memory.state_key or 'none'} type={memory.type} "
                f"subject={memory.subject} polarity={memory.polarity} "
                f"value={memory.value} raw_text={memory.raw_text or memory.value} "
                f"use_when={memory.use_when or []} "
                f"confirmation_question={memory.confirmation_question or 'none'}"
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
    lines.extend(["", render_runtime_receipt_prompt(pack.runtime_receipt)])
    return "\n".join(lines)


def render_runtime_receipt_prompt(receipt: dict[str, Any]) -> str:
    if not receipt:
        return "System Runtime Receipt:\n- status: completed\n- actions: none"
    lines = [
        "System Runtime Receipt:",
        f"- plan_id: {receipt.get('plan_id') or 'none'}",
        f"- status: {receipt.get('status') or 'unknown'}",
        f"- route_type: {receipt.get('route_type') or 'unknown'}",
        f"- intent: {receipt.get('intent') or 'unknown'}",
        "- Rule: use only completed receipt outputs as executed capability results.",
        "- Rule: never claim a blocked, failed, skipped, or absent action succeeded.",
        "Actions:",
    ]
    actions = receipt.get("actions")
    if not isinstance(actions, list) or not actions:
        lines.append("- none")
        return "\n".join(lines)
    for item in actions:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"- operation: {item.get('operation') or 'unknown'}",
                f"  action_id: {item.get('action_id') or 'none'}",
                f"  status: {item.get('status') or 'unknown'}",
                f"  duration_ms: {item.get('duration_ms') or 0}",
                "  business_input_json: "
                + _compact_json(item.get("business_input") or {}, max_length=1200),
            ]
        )
        if item.get("error"):
            lines.append(
                "  error: " + _compact_text(item.get("error"), max_length=1000)
            )
        if item.get("output") is not None:
            lines.append(
                "  output_json: "
                + _compact_json(item.get("output"), max_length=6000)
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


def _current_turn_constraints(
    policy: TurnPolicy,
    user_message: str,
    *,
    routing_decision: dict[str, Any] | None = None,
) -> list[str]:
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
    if policy.can_view_recommendation_history:
        constraints.append("recommendation_history_allowed_by_turn_policy")
    if policy.can_record_recommendation_signal:
        constraints.append("recommendation_signal_allowed_by_turn_policy")
    if policy.can_use_research_tools:
        constraints.append("research_tools_allowed_by_turn_policy")
    if routing_decision:
        requirements = routing_decision.get("requirements")
        if isinstance(requirements, dict):
            for name, required in requirements.items():
                constraints.append(
                    f"routing_requirement:{name}={'yes' if bool(required) else 'no'}"
                )
        routed_constraints = routing_decision.get("constraints")
        if isinstance(routed_constraints, list):
            for item in routed_constraints:
                if not isinstance(item, dict):
                    continue
                field = _compact_text(item.get("field"), max_length=100)
                operator = _compact_text(item.get("operator"), max_length=40)
                if not field:
                    continue
                constraints.append(
                    "routing_constraint:"
                    f"{field}:{operator or 'equals'}:"
                    f"{_compact_json(item.get('value'), max_length=300)}"
                )
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


def _compact_json(value: Any, *, max_length: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    return _compact_text(text, max_length=max_length)


def _receipt_payload(
    receipt: PlanReceipt | dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(receipt, PlanReceipt):
        return receipt.model_dump(mode="json")
    if isinstance(receipt, dict):
        return dict(receipt)
    return {}


def _action_plan_payload(
    plan: ActionPlan | dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(plan, ActionPlan):
        return plan.model_dump(mode="json")
    if isinstance(plan, dict):
        return dict(plan)
    return {}


def _embedded_routing_decision(
    plan_payload: dict[str, Any],
) -> dict[str, Any]:
    metadata = plan_payload.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    decision = metadata.get("routing_decision")
    if not isinstance(decision, dict):
        return {}
    return decision


def _embedded_routing_policy(plan_payload: dict[str, Any]) -> Any:
    return _embedded_routing_decision(plan_payload).get("policy")


def _validate_authoritative_policy(value: Any, *, source: str) -> TurnPolicy:
    try:
        return TurnPolicy.model_validate(value)
    except Exception as exc:
        raise ValueError(
            f"{source} is invalid; refusing legacy raw-text reclassification"
        ) from exc


def _memory_events_from_receipt(
    receipt: dict[str, Any],
    *,
    limit: int,
) -> list[MemoryEvent]:
    result: list[MemoryEvent] = []
    seen: set[UUID] = set()
    actions = receipt.get("actions")
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        if action.get("status") != "completed":
            continue
        output = action.get("output")
        if not isinstance(output, dict):
            continue
        candidates: list[Any] = []
        memories = output.get("memories")
        if isinstance(memories, list):
            for item in memories:
                if isinstance(item, dict) and isinstance(item.get("memory"), dict):
                    candidates.append(item["memory"])
                else:
                    candidates.append(item)
        if isinstance(output.get("memory"), dict):
            candidates.append(output["memory"])
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            try:
                event = MemoryEvent.model_validate(candidate)
            except Exception:
                continue
            if event.id is not None and event.id in seen:
                continue
            if event.id is not None:
                seen.add(event.id)
            result.append(event)
            if len(result) >= max(0, limit):
                return result
    return result


def _denied_memories_from_receipt(receipt: dict[str, Any]) -> list[MemoryEvent]:
    denied: list[MemoryEvent] = []
    actions = receipt.get("actions")
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        output = action.get("output")
        if not isinstance(output, dict):
            continue
        candidates = output.get("denied_memories")
        for item in candidates if isinstance(candidates, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                denied.append(MemoryEvent.model_validate(item))
            except Exception:
                continue
    return denied


def _research_state_from_receipt(
    receipt: dict[str, Any],
) -> ResearchStateSlice | None:
    actions = receipt.get("actions")
    for action in reversed(actions if isinstance(actions, list) else []):
        if not isinstance(action, dict) or action.get("status") != "completed":
            continue
        output = action.get("output")
        if not isinstance(output, dict):
            continue
        state_payload = output.get("state")
        run_payload = output.get("run")
        if not isinstance(state_payload, dict):
            nested = output.get("research_state")
            if isinstance(nested, dict):
                state_payload = nested.get("state")
                run_payload = nested.get("run")
        if not isinstance(state_payload, dict) or not isinstance(run_payload, dict):
            continue
        try:
            return ResearchStateSlice(
                run_id=run_payload.get("id"),
                objective=str(run_payload.get("objective") or ""),
                status=str(run_payload.get("status") or ""),
                mode=str(run_payload.get("mode") or ""),
                subquestions=list(state_payload.get("subquestions") or [])[:8],
                known_facts=list(state_payload.get("known_facts") or [])[:8],
                gaps=list(state_payload.get("gaps") or [])[:8],
                conflicts=list(state_payload.get("conflicts") or [])[:8],
                exhausted_queries=list(state_payload.get("exhausted_queries") or [])[:8],
                next_actions=list(state_payload.get("next_actions") or [])[:8],
                evidence_ids=list(state_payload.get("evidence_ids") or [])[:20],
                budget=dict(state_payload.get("budget") or {}),
                stop_criteria=list(state_payload.get("stop_criteria") or [])[:8],
                metadata={"source": "plan_receipt"},
            )
        except Exception:
            continue
    return None


def _join_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"
