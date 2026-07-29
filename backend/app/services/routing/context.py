from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.schemas.chat import UserInput
from app.services.conversation.contracts import ConversationTurn
from app.services.routing.interaction_contracts import (
    BusinessRoutingContext,
    DecisionConstraint,
    PendingMemoryWriteContext,
)
from app.services.routing.clarification import (
    might_be_memory_clarification_answer,
)


logger = logging.getLogger(__name__)

_FOLLOW_UP_RE = re.compile(
    r"^(?:再|继续|接着|还有|这(?:本|个|些)|那(?:本|个|些)|它|类似|"
    r"换一批|上面|刚才|more\b|continue\b|another\b|that\b|those\b)",
    re.IGNORECASE,
)
_MEMORY_REFERENCE_RE = re.compile(
    r"^(?:先)?(?:请你|请|帮我)?(?:记住|记一下|记下来|保存)"
    r"(?:我的|这个|那个|这些|那些|它|他|她|这件事|那件事)",
    re.IGNORECASE,
)
_CONVERSATION_RECALL_CONTEXT_RE = re.compile(
    r"(?:我刚才|我上面|我之前刚刚|你刚才|你上面).*(?:说|讲|问|告诉|回答)|"
    r"(?:刚才|上面).*(?:说|聊)",
    re.IGNORECASE,
)
_QUOTED_MESSAGE_RE = re.compile(r"^>\s*(?P<quoted>.+?)\n\n", re.DOTALL)
_BOOK_TITLE_RE = re.compile(r"《(?P<title>[^》]{1,100})》")


def routing_text(user_input: UserInput) -> str:
    """Return the user-authored current clause, excluding display-only quotes."""

    custom = user_input.custom_data or {}
    current = " ".join(str(custom.get("user_content") or "").split()).strip()
    return current or user_input.content


def needs_business_context(user_input: UserInput) -> bool:
    """Keep checkpoint reads off the ordinary Layer-0 request path."""

    text = routing_text(user_input)
    custom = user_input.custom_data or {}
    return bool(
        _FOLLOW_UP_RE.search(text)
        or _MEMORY_REFERENCE_RE.search(text)
        or _CONVERSATION_RECALL_CONTEXT_RE.search(text)
        or might_be_memory_clarification_answer(text)
        or custom.get("quoted_message_id")
        or custom.get("routing_context")
    )


async def project_business_routing_context(
    *,
    user_input: UserInput,
    agent: CompiledStateGraph | None,
) -> BusinessRoutingContext:
    """Project identity-free follow-up context from explicit or checkpoint data.

    This adapter may use a system-owned thread identifier to read the existing
    checkpoint, but the returned routing contract contains business text only.
    Routing providers never receive the identifier.
    """

    explicit = _explicit_context(user_input.custom_data or {})
    if not needs_business_context(user_input):
        return explicit

    recent_user_messages = list(explicit.recent_user_messages)
    conversation_turns = list(explicit.conversation_turns)
    previous_primary_intent = explicit.previous_primary_intent
    previous_constraints = list(explicit.previous_constraints)
    active_subject = explicit.active_subject or _quoted_subject(user_input.content)
    pending_memory_write = explicit.pending_memory_write

    if agent is not None:
        try:
            state = await agent.aget_state(
                RunnableConfig(
                    {"configurable": {"thread_id": str(user_input.thread_id)}}
                )
            )
            messages = list((state.values or {}).get("messages", []))
            checkpoint_context = _context_from_messages(messages)
            if not recent_user_messages:
                recent_user_messages = checkpoint_context.recent_user_messages
            if not conversation_turns:
                conversation_turns = checkpoint_context.conversation_turns
            previous_primary_intent = (
                previous_primary_intent
                or checkpoint_context.previous_primary_intent
            )
            if not previous_constraints:
                previous_constraints = checkpoint_context.previous_constraints
            active_subject = active_subject or checkpoint_context.active_subject
            pending_memory_write = (
                pending_memory_write
                or checkpoint_context.pending_memory_write
            )
        except Exception as exc:
            logger.info("Routing context projection unavailable: %s", exc)

    return BusinessRoutingContext(
        recent_user_messages=recent_user_messages[-8:],
        conversation_turns=conversation_turns[-16:],
        previous_primary_intent=previous_primary_intent,
        active_subject=active_subject,
        previous_constraints=previous_constraints,
        pending_memory_write=pending_memory_write,
    )


def _explicit_context(custom: dict[str, Any]) -> BusinessRoutingContext:
    raw = custom.get("routing_context")
    if not isinstance(raw, dict):
        return BusinessRoutingContext()
    allowed = {
        "recent_user_messages",
        "conversation_turns",
        "previous_primary_intent",
        "active_subject",
        "previous_constraints",
        "pending_memory_write",
    }
    payload = {key: value for key, value in raw.items() if key in allowed}
    try:
        return BusinessRoutingContext.model_validate(payload)
    except Exception:
        return BusinessRoutingContext()


def _context_from_messages(
    messages: Sequence[BaseMessage],
) -> BusinessRoutingContext:
    recent_user_messages = [
        _message_text(message)
        for message in messages
        if isinstance(message, HumanMessage)
    ]
    recent_user_messages = [item for item in recent_user_messages if item][-8:]
    ordered_messages = [
        (message, _message_text(message))
        for message in messages
        if isinstance(message, (HumanMessage, AIMessage))
    ]
    ordered_messages = [
        (message, text) for message, text in ordered_messages if text
    ][-16:]
    conversation_turns = [
        ConversationTurn(
            role="user" if isinstance(message, HumanMessage) else "assistant",
            turn_offset=index - len(ordered_messages),
            content=text,
        )
        for index, (message, text) in enumerate(ordered_messages)
    ]

    previous_primary_intent: str | None = None
    previous_constraints: list[DecisionConstraint] = []
    for message in reversed(messages):
        plan = _action_plan_from_message(message)
        if not plan:
            continue
        previous_primary_intent = str(plan.get("intent") or "").strip() or None
        routing = _routing_decision_from_plan(plan)
        previous_constraints = _decision_constraints(
            routing.get("constraints") if routing else None
        )
        break

    active_subject = _active_subject(recent_user_messages[-1]) if recent_user_messages else None
    pending_memory_write: PendingMemoryWriteContext | None = None
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        pending_memory_write = _pending_memory_write_from_message(message)
        break
    return BusinessRoutingContext(
        recent_user_messages=recent_user_messages,
        conversation_turns=conversation_turns,
        previous_primary_intent=previous_primary_intent,
        active_subject=active_subject,
        previous_constraints=previous_constraints,
        pending_memory_write=pending_memory_write,
    )


def _message_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return " ".join(content.split()).strip()[:500]
    return " ".join(str(content or "").split()).strip()[:500]


def _action_plan_from_message(message: BaseMessage) -> dict[str, Any]:
    additional = getattr(message, "additional_kwargs", None)
    if not isinstance(additional, dict):
        return {}
    custom = additional.get("custom_data")
    if isinstance(custom, dict) and isinstance(custom.get("action_plan"), dict):
        return dict(custom["action_plan"])
    if isinstance(additional.get("action_plan"), dict):
        return dict(additional["action_plan"])
    return {}


def _pending_memory_write_from_message(
    message: BaseMessage,
) -> PendingMemoryWriteContext | None:
    additional = getattr(message, "additional_kwargs", None)
    if not isinstance(additional, dict):
        return None
    custom = additional.get("custom_data")
    receipt = (
        custom.get("plan_receipt")
        if isinstance(custom, dict)
        else additional.get("plan_receipt")
    )
    if not isinstance(receipt, dict):
        return None
    actions = receipt.get("actions")
    if not isinstance(actions, list):
        return None
    for action in reversed(actions):
        if not isinstance(action, dict):
            continue
        if action.get("operation") != "process_memory_write_request":
            continue
        output = action.get("output")
        if not isinstance(output, dict):
            return None
        if output.get("status") != "clarification_required":
            return None
        pending = output.get("pending_clarification")
        if not isinstance(pending, dict):
            return None
        try:
            return PendingMemoryWriteContext.model_validate(pending)
        except Exception:
            return None
    return None


def _routing_decision_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    metadata = plan.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    decision = metadata.get("routing_decision")
    return dict(decision) if isinstance(decision, dict) else {}


def _decision_constraints(value: Any) -> list[DecisionConstraint]:
    if not isinstance(value, list):
        return []
    result: list[DecisionConstraint] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            result.append(DecisionConstraint.model_validate(item))
        except Exception:
            continue
    return result


def _quoted_subject(text: str) -> str | None:
    match = _QUOTED_MESSAGE_RE.search(str(text or ""))
    return _active_subject(match.group("quoted")) if match else None


def _active_subject(text: str) -> str | None:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return None
    title = _BOOK_TITLE_RE.search(normalized)
    if title:
        return f"《{title.group('title')}》"
    return normalized[:200]
