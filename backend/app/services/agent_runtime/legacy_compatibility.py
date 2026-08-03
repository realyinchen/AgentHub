"""The sole execution adapter for quarantined routing-decision plans."""

from __future__ import annotations

import json
from typing import Any

from app.schemas.chat import UserInput
from app.services.agent_core.core_capabilities import CoreCapabilityAvailability
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlannedAction,
)
from app.services.agent_runtime.legacy_admission import (
    admit_legacy_context_operation,
)
from app.services.agent_runtime.legacy_availability import (
    LegacyRuntimeAvailability,
)

_CONTEXT_OPERATIONS = frozenset(
    {
        "process_memory_write_request",
        "recall_recent_conversation",
        "search_memory",
    }
)
_RETIRED_DIRECT_MEMORY_WRITES = frozenset({"remember_memory", "revise_memory"})
_USER_ID_OPERATIONS = frozenset(
    {
        "process_memory_write_request",
        "search_memory",
        "remember_memory",
        "revise_memory",
        "forget_memory",
        "plan_book_assistant_turn",
        "search_books",
        "get_recommendation_history",
        "remember_reading_preference",
        "record_book_feedback",
        "record_recommendation_signal",
        "start_research",
        "inspect_research_state",
        "search_research",
        "visit_source",
        "add_evidence",
        "update_research_state",
        "finish_research",
        "collect_research_sources",
        "build_research_report",
        "finalize_research_answer",
        "plan_recommendation_research_workflow",
        "run_recommendation_research_workflow",
        "run_research_harness",
    }
)
_THREAD_ID_OPERATIONS = frozenset(
    {
        "process_memory_write_request",
        "remember_memory",
        "forget_memory",
        "record_book_feedback",
        "record_recommendation_signal",
        "start_research",
        "run_recommendation_research_workflow",
        "run_research_harness",
    }
)
_ALLOWED_OPERATIONS = frozenset(
    {
        *_CONTEXT_OPERATIONS,
        *_USER_ID_OPERATIONS,
        "web_search",
        "plan_research_search",
        "acquire_research_sources",
        "evaluate_research_gaps",
        "synthesize_research_answer",
        "publish_research_answer",
    }
)


class LegacyRoutingRuntimeCompatibility:
    """Admit and execute only plans produced by the retired router."""

    def __init__(
        self,
        *,
        availability: LegacyRuntimeAvailability | None = None,
        core_availability: CoreCapabilityAvailability | None = None,
        external_runtime: Any | None = None,
    ) -> None:
        self._availability = availability or LegacyRuntimeAvailability.from_settings()
        self._core = core_availability or CoreCapabilityAvailability.from_settings()
        self._external_runtime = external_runtime

    def handles(self, plan: ActionPlan, action: PlannedAction) -> bool:
        del action
        return plan.source == "routing_decision"

    def admit(
        self,
        plan: ActionPlan,
        action: PlannedAction,
    ) -> tuple[bool, str]:
        if not self.handles(plan, action):
            return False, "legacy_plan_source_required"
        if action.operation not in _ALLOWED_OPERATIONS:
            return False, "legacy_operation_not_registered"
        if action.operation in _RETIRED_DIRECT_MEMORY_WRITES:
            return False, "chat_memory_write_requires_precommit_pipeline"
        if action.operation == "process_memory_write_request" and (
            self._core.memory_write or not self._availability.memory_write_compat
        ):
            return False, "legacy_memory_write_disabled_for_r6"

        policy = _policy_from_plan(plan)
        if plan.policy and (
            policy is None or action.operation not in set(policy.allowed_tools)
        ):
            return False, "operation_not_authorized_by_routing_policy"
        flag = {
            "web_search": "can_use_web_search",
            "acquire_research_sources": "can_use_web_search",
            "search_books": "can_search_books",
            "get_recommendation_history": "can_view_recommendation_history",
            "start_research": "can_start_research",
        }.get(action.operation)
        if flag and (policy is None or not bool(getattr(policy, flag, False))):
            return False, f"turn_policy_{flag}_false"
        if action.operation in _CONTEXT_OPERATIONS:
            return admit_legacy_context_operation(plan, action)

        external = self._external_capability_runtime(action.operation)
        if external is not None:
            return external.admit(action.operation)
        return True, "legacy_routing_compatibility"

    async def execute(
        self,
        plan: ActionPlan,
        action: PlannedAction,
        *,
        context: ExecutionContext,
        user_input: UserInput | None,
        previous: list[ActionReceipt],
    ) -> Any:
        if not self.handles(plan, action):
            raise RuntimeError("legacy_plan_source_required")
        if action.operation == "process_memory_write_request":
            from app.services.agent_runtime.legacy_operations import (
                process_memory_write_request,
            )

            return await process_memory_write_request(
                action,
                context=context,
                user_input=user_input,
            )
        if action.operation == "recall_recent_conversation":
            from app.services.agent_runtime.legacy_operations import (
                recall_conversation,
            )

            return recall_conversation(action, context=context)
        if action.operation == "search_memory":
            from app.services.agent_runtime.legacy_operations import search_memory

            return await search_memory(action, context=context)

        external = self._external_capability_runtime(action.operation)
        if external is not None:
            return await external.execute(
                action.operation,
                action.arguments,
                context=context,
                previous=previous,
            )

        special = await _execute_research_dependency_action(
            action,
            context=context,
            previous=previous,
        )
        if special is not None:
            return special
        tool = _resolve_internal_tool(action.operation)
        raw = await tool.ainvoke(
            _inject_system_arguments(action.operation, action.arguments, context)
        )
        return _json_or_text(raw)

    def injected_fields(
        self,
        action: PlannedAction,
        context: ExecutionContext,
    ) -> tuple[str, ...]:
        result: list[str] = []
        if action.operation in _USER_ID_OPERATIONS:
            result.append("user_id")
        if action.operation in _THREAD_ID_OPERATIONS and context.thread_id is not None:
            result.append("thread_id")
        return tuple(result)

    def _external_capability_runtime(self, operation: str) -> Any | None:
        from app.services.external_capabilities.operation_registry import (
            descriptor_for_operation,
        )

        if descriptor_for_operation(operation) is None:
            return None
        if self._external_runtime is None:
            from app.services.external_capabilities.runtime import (
                get_external_capability_runtime,
            )

            self._external_runtime = get_external_capability_runtime()
        return self._external_runtime


async def _execute_research_dependency_action(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    previous: list[ActionReceipt],
) -> Any | None:
    from app.services.research.runtime_dependencies import (
        execute_research_dependency,
    )

    return await execute_research_dependency(
        action,
        context=context,
        previous=previous,
    )


def _resolve_internal_tool(operation: str) -> Any:
    from app.agents import tools as agent_tools

    if operation == "web_search":
        return agent_tools.create_web_search()
    tool = getattr(agent_tools, operation, None)
    if tool is None:
        raise LookupError(f"legacy runtime operation is not registered: {operation}")
    return tool


def _inject_system_arguments(
    operation: str,
    business_input: dict[str, Any],
    context: ExecutionContext,
) -> dict[str, Any]:
    args = dict(business_input)
    if operation in _USER_ID_OPERATIONS:
        args["user_id"] = str(context.user_id)
    if operation in _THREAD_ID_OPERATIONS and context.thread_id is not None:
        args["thread_id"] = str(context.thread_id)
    return {key: value for key, value in args.items() if value is not None}


def _policy_from_plan(plan: ActionPlan) -> Any | None:
    from app.services.book_intent import TurnPolicy, build_turn_policy

    if plan.policy:
        try:
            return TurnPolicy.model_validate(plan.policy)
        except Exception:
            pass
    return build_turn_policy(plan.goal)


def _json_or_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


__all__ = ["LegacyRoutingRuntimeCompatibility"]
