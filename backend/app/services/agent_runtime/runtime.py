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
from app.services.memory import get_memory_orchestrator
from app.services.memory.user_state import (
    decide_user_state_capture,
    persist_raw_user_state,
    schedule_pending_user_state_organization,
)
from app.services.profile_memory_capture import capture_explicit_profile_memories
from app.utils.turn_context import user_message_scope


logger = logging.getLogger(__name__)

_USER_ID_OPERATIONS = frozenset(
    {
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
            if action.operation == "capture_user_state":
                output = await _capture_user_state(
                    action,
                    context=context,
                    user_input=user_input,
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


async def _capture_user_state(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    user_input: UserInput | None,
) -> dict[str, Any]:
    if user_input is None:
        raise RuntimeError("capture_user_state requires the current user input")
    capture_mode = str(action.arguments.get("capture_mode") or "raw_first")
    raw_text = str(action.arguments.get("raw_text") or user_input.content).strip()

    if capture_mode == "deterministic":
        capture = await capture_explicit_profile_memories(user_input)
        if capture.captured_count > 0:
            return {
                "status": "completed",
                "capture_mode": "deterministic",
                "captured_count": capture.captured_count,
                "memories": capture.memories,
                "memory_admission": _capture_admission_summary(capture.memories),
            }

    persisted = await persist_raw_user_state(
        user_id=context.user_id,
        thread_id=context.thread_id,
        raw_text=raw_text,
        explicit=bool(action.arguments.get("explicit")),
        organizer_model_id=context.model_name,
        route_type=str(context.metadata.get("route_type") or "slow_path"),
    )
    return {
        "status": persisted.status,
        "capture_mode": "raw_first",
        "memory": (
            persisted.memory.model_dump(mode="json") if persisted.memory else None
        ),
        "memory_id": str(persisted.memory.id) if persisted.memory and persisted.memory.id else None,
        "organization_scheduled": persisted.organization_scheduled,
        "memory_admission": [
            {
                "decision": "allow" if persisted.memory is not None else "skip",
                "status": (
                    persisted.memory.state_status if persisted.memory else "skipped"
                ),
                "memory_id": (
                    str(persisted.memory.id)
                    if persisted.memory is not None and persisted.memory.id
                    else None
                ),
            }
        ],
    }


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
        if not memories:
            pending = await orchestrator.list_current_memories(
                user_id=context.user_id,
                memory_types=memory_types if isinstance(memory_types, list) else None,
                limit=min(limit, 20),
            )
            memories = [
                item
                for item in pending.memories
                if item.state_status in {"pending", "needs_confirmation"}
            ][:3]
    else:
        current = await orchestrator.list_current_memories(
            user_id=context.user_id,
            memory_types=memory_types if isinstance(memory_types, list) else None,
            limit=limit,
        )
        memories = list(current.memories)
        profile = {}

    try:
        await schedule_pending_user_state_organization(context.user_id, limit=10)
    except Exception as exc:
        logger.debug("Unable to schedule pending memory organization: %s", exc)

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
    operation = action.operation
    needs_runtime_dependency = (
        operation == "collect_research_sources"
        and not action.arguments.get("sources")
    ) or (
        operation == "add_evidence" and not action.arguments.get("claim")
    ) or (
        operation in {"build_research_report", "finalize_research_answer"}
        and not action.arguments.get("run_id")
    )
    if not needs_runtime_dependency:
        return None

    from app.services.turn_execution import (
        PreActionResult,
        TurnToolDecision,
        _execute_add_research_evidence,
        _execute_build_research_report,
        _execute_collect_research_sources,
        _execute_finalize_research_answer,
    )

    decision = TurnToolDecision(
        tool_name=operation,
        decision="required",
        reason=action.reason,
        action_id=action.action_id,
        args=_inject_system_arguments(operation, action.arguments, context),
    )
    prior = [
        PreActionResult(
            action_id=item.action_id,
            tool_name=item.operation,
            status=(
                "ok"
                if item.status == "completed"
                else "skipped"
                if item.status == "skipped"
                else "failed"
            ),
            input=item.business_input,
            output=item.output,
            error=item.error,
            duration_ms=item.duration_ms,
            metadata=item.metadata,
        )
        for item in previous
    ]
    if operation == "collect_research_sources":
        result = await _execute_collect_research_sources(decision, prior)
    elif operation == "add_evidence":
        result = await _execute_add_research_evidence(decision, prior)
    elif operation == "build_research_report":
        result = await _execute_build_research_report(decision, prior)
    else:
        result = await _execute_finalize_research_answer(decision, prior)
    if result.status == "failed":
        return {"status": "failed", "error": result.error}
    if result.status == "skipped":
        return {"status": "skipped", "error": result.error, "output": result.output}
    return result.output


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

    flag = {
        "web_search": "can_use_web_search",
        "search_books": "can_search_books",
        "get_recommendation_history": "can_view_recommendation_history",
        "start_research": "can_start_research",
    }.get(action.operation)
    if flag and not bool(getattr(policy, flag)):
        return False, f"turn_policy_{flag}_false"

    if action.operation == "search_memory" and plan.source != "model_tool_call":
        return True, "app_plan_memory_read"
    if action.operation == "capture_user_state":
        raw_text = " ".join(
            str(action.arguments.get("raw_text") or "").split()
        ).strip()
        goal = " ".join(str(plan.goal or "").split()).strip()
        if not raw_text or raw_text not in goal:
            return False, "memory_raw_text_must_be_user_authored"
        decision = decide_user_state_capture(raw_text)
        if not decision.should_capture:
            return False, "memory_candidate_is_not_durable_user_state"
        return True, (
            "deterministic_user_state_capture"
            if plan.source == "deterministic_rule"
            else "planned_user_state_capture"
        )
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
