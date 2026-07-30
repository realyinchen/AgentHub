from __future__ import annotations

from typing import Any

from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import (
    ExecutionContext,
    PlannedAction,
)
from app.services.conversation.contracts import (
    ConversationTurn,
    ConversationWindow,
)
from app.services.conversation.recall import (
    recall_recent_conversation,
)
from app.services.memory import get_memory_orchestrator
from app.services.memory.write_contracts import MemoryWriteRequest
from app.services.memory.write_coordinator import MemoryWriteCoordinator


async def process_memory_write_request(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    user_input: UserInput | None,
) -> dict[str, Any]:
    """Compatibility execution for pre-R6 routing plans only."""

    if user_input is None:
        raise RuntimeError(
            "process_memory_write_request requires the current user input"
        )
    request_payload = action.arguments.get("request")
    if not isinstance(request_payload, dict):
        raise ValueError("memory write action requires a typed request")
    request = MemoryWriteRequest.model_validate(request_payload)
    outcome = await MemoryWriteCoordinator().process(
        request,
        user_input=user_input,
        conversation=conversation_window(context),
        user_id=context.user_id,
        thread_id=context.thread_id,
        model_id=context.model_name,
    )
    return outcome.model_dump(mode="json")


def recall_conversation(
    action: PlannedAction,
    *,
    context: ExecutionContext,
) -> dict[str, Any]:
    """Compatibility recall over the old routing-context projection."""

    result = recall_recent_conversation(
        conversation_window(context),
        query=str(action.arguments.get("query") or ""),
        limit=int(action.arguments.get("limit") or 4),
    )
    return result.model_dump(mode="json")


async def search_memory(
    action: PlannedAction,
    *,
    context: ExecutionContext,
) -> dict[str, Any]:
    """Compatibility read over the old memory projection."""

    query = str(action.arguments.get("query") or "").strip()
    lookup_kind = str(action.arguments.get("lookup_kind") or "generic")
    limit = max(1, min(int(action.arguments.get("limit") or 20), 100))
    memory_types = action.arguments.get("memory_types")
    orchestrator = get_memory_orchestrator()

    if query:
        result = await orchestrator.search_memory(
            user_id=context.user_id,
            query=query,
            memory_types=memory_types if isinstance(memory_types, list) else None,
            limit=limit,
        )
        memories = list(result.relevant_events)
        profile = result.model_dump(mode="json")
    else:
        current = await orchestrator.list_current_memories(
            user_id=context.user_id,
            memory_types=memory_types if isinstance(memory_types, list) else None,
            limit=limit,
        )
        memories = list(current.memories)
        profile = {}

    return {
        "status": "completed",
        "result_mode": "memory_recall_receipt",
        "query": query,
        "lookup_kind": lookup_kind,
        "result_count": len(memories),
        "memories": [item.model_dump(mode="json") for item in memories],
        "profile": profile,
        "selection": {
            "strategy": "query_relevance" if query else "bounded_current_state",
            "limit": limit,
            "hidden_context_read": False,
        },
    }


def conversation_window(context: ExecutionContext) -> ConversationWindow:
    """Build only the compatibility window consumed by old operations."""

    raw_turns = context.metadata.get("conversation_turns")
    turns: list[ConversationTurn] = []
    if isinstance(raw_turns, list):
        for item in raw_turns:
            try:
                turns.append(ConversationTurn.model_validate(item))
            except Exception:
                continue
    if not turns:
        recent = context.metadata.get("recent_user_messages")
        messages = recent if isinstance(recent, list) else []
        turns = [
            ConversationTurn(
                role="user",
                turn_offset=index - len(messages),
                content=str(message),
            )
            for index, message in enumerate(messages)
            if str(message or "").strip()
        ]
    return ConversationWindow(turns=turns[-16:])


__all__ = [
    "conversation_window",
    "process_memory_write_request",
    "recall_conversation",
    "search_memory",
]
