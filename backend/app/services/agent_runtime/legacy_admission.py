from __future__ import annotations

from app.services.agent_runtime.contracts import ActionPlan, PlannedAction
from app.services.memory.write_contracts import MemoryWriteRequest


def admit_legacy_context_operation(
    plan: ActionPlan,
    action: PlannedAction,
) -> tuple[bool, str]:
    """Validate only pre-R6 memory and conversation compatibility actions."""

    if action.operation == "search_memory":
        return True, "app_plan_memory_read"
    if action.operation == "recall_recent_conversation":
        return True, "app_plan_conversation_read"
    if action.operation != "process_memory_write_request":
        return False, "legacy_context_operation_unknown"

    request_payload = action.arguments.get("request")
    if not isinstance(request_payload, dict):
        return False, "memory_write_request_missing"
    try:
        request = MemoryWriteRequest.model_validate(request_payload)
    except Exception:
        return False, "memory_write_request_invalid"
    goal = " ".join(str(plan.goal or "").split()).strip()
    if request.utterance not in goal:
        return False, "memory_request_must_be_user_authored"
    return True, "precommit_memory_pipeline"


__all__ = ["admit_legacy_context_operation"]
