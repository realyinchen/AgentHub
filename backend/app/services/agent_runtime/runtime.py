from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlanReceipt,
    PlannedAction,
)
from app.services.book_intent import TurnPolicy, build_turn_policy
from app.services.conversation import (
    ConversationTurn,
    ConversationWindow,
    recall_recent_conversation,
)
from app.services.memory import get_memory_orchestrator
from app.services.memory.write_contracts import MemoryWriteRequest
from app.services.memory.write_coordinator import MemoryWriteCoordinator
from app.utils.turn_context import user_message_scope


logger = logging.getLogger(__name__)

_RETIRED_CHAT_MEMORY_WRITE_OPERATIONS = frozenset(
    {"remember_memory", "revise_memory"}
)

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


class SystemRuntime:
    """The only component allowed to turn a plan into side effects/results."""

    async def execute(
        self,
        plan: ActionPlan,
        *,
        context: ExecutionContext,
        user_input: UserInput | None = None,
    ) -> PlanReceipt:
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        receipts: list[ActionReceipt] = []

        user_message = (
            user_input.content
            if user_input is not None
            else str(context.metadata.get("user_message") or plan.goal)
        )
        policy = _policy_from_plan(plan, user_message)
        with user_message_scope(user_message):
            for action in plan.actions:
                dependency_failure = _dependency_failure(action, receipts)
                if dependency_failure:
                    receipts.append(
                        ActionReceipt(
                            action_id=action.action_id,
                            capability=action.capability,
                            operation=action.operation,
                            status="skipped",
                            business_input=action.arguments,
                            error=dependency_failure,
                            admitted=False,
                            metadata={"dependency_gate": "failed"},
                        )
                    )
                    continue

                admitted, reason = _admit_action(plan, action, policy)
                if not admitted:
                    receipts.append(
                        ActionReceipt(
                            action_id=action.action_id,
                            capability=action.capability,
                            operation=action.operation,
                            status="blocked",
                            business_input=action.arguments,
                            error=reason,
                            admitted=False,
                            metadata={"policy_gate": reason},
                        )
                    )
                    continue

                receipt = await self._execute_action(
                    action,
                    context=context,
                    user_input=user_input,
                    previous=receipts,
                )
                receipts.append(receipt)

        duration_ms = int((time.perf_counter() - started) * 1000)
        status = _plan_status(receipts)
        receipt = PlanReceipt(
            plan_id=plan.plan_id,
            request_id=context.request_id,
            route_type=plan.route_type,
            intent=plan.intent,
            planner_used=plan.planner_used,
            status=status,
            actions=receipts,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            metadata={
                "plan_source": plan.source,
                "execution_order": [item.action_id for item in receipts],
                "system_context_injected": [
                    "user_id",
                    "thread_id",
                    "request_id",
                ],
            },
        )
        logger.info(
            "agent_runtime_receipt route_type=%s intent=%s plan_id=%s "
            "planner_used=%s status=%s duration_ms=%d actions=%s",
            plan.route_type,
            plan.intent,
            plan.plan_id,
            plan.planner_used,
            receipt.status,
            duration_ms,
            [
                {
                    "operation": item.operation,
                    "status": item.status,
                    "duration_ms": item.duration_ms,
                }
                for item in receipts
            ],
        )
        return receipt

    async def _execute_action(
        self,
        action: PlannedAction,
        *,
        context: ExecutionContext,
        user_input: UserInput | None,
        previous: list[ActionReceipt],
    ) -> ActionReceipt:
        started = time.perf_counter()
        try:
            if action.operation == "process_memory_write_request":
                output = await _process_memory_write_request(
                    action,
                    context=context,
                    user_input=user_input,
                )
            elif action.operation == "recall_recent_conversation":
                output = _recall_recent_conversation(
                    action,
                    context=context,
                )
            elif action.operation == "search_memory":
                output = await _search_memory(action, context=context)
            else:
                output = await _execute_tool_operation(
                    action,
                    context=context,
                    previous=previous,
                )
            status, error = _output_status(output)
            return ActionReceipt(
                action_id=action.action_id,
                capability=action.capability,
                operation=action.operation,
                status=status,
                business_input=action.arguments,
                output=output,
                error=error,
                duration_ms=int((time.perf_counter() - started) * 1000),
                admitted=True,
                metadata={
                    "runtime_dispatch": "system_runtime",
                    "injected_fields": _injected_field_names(action.operation, context),
                },
            )
        except Exception as exc:
            logger.exception("System runtime action failed: %s", action.operation)
            return ActionReceipt(
                action_id=action.action_id,
                capability=action.capability,
                operation=action.operation,
                status="failed",
                business_input=action.arguments,
                error=str(exc) or exc.__class__.__name__,
                duration_ms=int((time.perf_counter() - started) * 1000),
                admitted=True,
                metadata={"runtime_dispatch": "system_runtime"},
            )


async def _process_memory_write_request(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    user_input: UserInput | None,
) -> dict[str, Any]:
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
        conversation=_conversation_window(context),
        user_id=context.user_id,
        thread_id=context.thread_id,
        model_id=context.model_name,
    )
    return outcome.model_dump(mode="json")


def _recall_recent_conversation(
    action: PlannedAction,
    *,
    context: ExecutionContext,
) -> dict[str, Any]:
    result = recall_recent_conversation(
        _conversation_window(context),
        query=str(action.arguments.get("query") or ""),
        limit=int(action.arguments.get("limit") or 4),
    )
    return result.model_dump(mode="json")


def _conversation_window(context: ExecutionContext) -> ConversationWindow:
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


async def _search_memory(
    action: PlannedAction,
    *,
    context: ExecutionContext,
) -> dict[str, Any]:
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


async def _execute_tool_operation(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    previous: list[ActionReceipt],
) -> Any:
    special = await _execute_research_dependency_action(
        action,
        context=context,
        previous=previous,
    )
    if special is not None:
        return special

    tool = _resolve_internal_tool(action.operation)
    args = _inject_system_arguments(action.operation, action.arguments, context)
    raw = await tool.ainvoke(args)
    return _json_or_text(raw)


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
        raise LookupError(f"runtime operation is not registered: {operation}")
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


def _injected_field_names(operation: str, context: ExecutionContext) -> list[str]:
    result: list[str] = []
    if operation in _USER_ID_OPERATIONS:
        result.append("user_id")
    if operation in _THREAD_ID_OPERATIONS and context.thread_id is not None:
        result.append("thread_id")
    return result


def _admit_action(
    plan: ActionPlan,
    action: PlannedAction,
    policy: TurnPolicy,
) -> tuple[bool, str]:
    if action.operation in set(plan.forbidden_operations):
        return False, "operation_forbidden_by_action_plan"
    if action.operation in _RETIRED_CHAT_MEMORY_WRITE_OPERATIONS:
        return False, "chat_memory_write_requires_precommit_pipeline"
    if plan.policy and action.operation not in set(policy.allowed_tools):
        return False, "operation_not_authorized_by_routing_policy"

    flag = {
        "web_search": "can_use_web_search",
        "acquire_research_sources": "can_use_web_search",
        "search_books": "can_search_books",
        "get_recommendation_history": "can_view_recommendation_history",
        "start_research": "can_start_research",
    }.get(action.operation)
    if flag and not bool(getattr(policy, flag)):
        return False, f"turn_policy_{flag}_false"

    if action.operation == "search_memory":
        return True, "app_plan_memory_read"
    if action.operation == "process_memory_write_request":
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
    if action.operation == "recall_recent_conversation":
        return True, "app_plan_conversation_read"
    return True, "admitted"


def _policy_from_plan(plan: ActionPlan, user_message: str) -> TurnPolicy:
    if plan.policy:
        try:
            return TurnPolicy.model_validate(plan.policy)
        except Exception:
            pass
    return build_turn_policy(user_message)


def _dependency_failure(
    action: PlannedAction,
    receipts: list[ActionReceipt],
) -> str:
    if not action.depends_on:
        return ""
    by_id = {item.action_id: item for item in receipts}
    for dependency in action.depends_on:
        receipt = by_id.get(dependency)
        if receipt is None:
            return f"dependency has no receipt: {dependency}"
        if receipt.status != "completed":
            return f"dependency did not complete: {dependency}"
    return ""


def _output_status(output: Any) -> tuple[str, str]:
    payload = output if isinstance(output, dict) else {}
    status = str(payload.get("status") or "").lower()
    error = str(payload.get("error") or "")
    if status in {"tool_blocked", "blocked", "denied", "needs_confirmation"}:
        return "blocked", error or status
    if status in {"failed", "error", "timeout", "unavailable"}:
        return "failed", error or status
    if status in {"skipped", "empty_result"}:
        return "skipped", error or status
    return "completed", ""


def _plan_status(receipts: list[ActionReceipt]) -> str:
    if not receipts:
        return "completed"
    statuses = {item.status for item in receipts}
    if statuses == {"completed"}:
        return "completed"
    if statuses == {"blocked"}:
        return "blocked"
    if "completed" in statuses:
        return "partial"
    return "failed"


def _capture_admission_summary(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        candidate = item.get("candidate") or {}
        decision = item.get("decision") or {}
        memory = item.get("memory") or {}
        result.append(
            {
                "type": candidate.get("type"),
                "subject": candidate.get("subject"),
                "decision": decision.get("decision"),
                "reason": decision.get("reason"),
                "memory_id": memory.get("id"),
            }
        )
    return result


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
