from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.infra.database import get_database
from app.schemas.chat import UserInput
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlanReceipt,
    PlannedAction,
)
from app.services.agent_runtime.ledger import (
    ExecutionLedger,
    action_idempotency_key,
)
from app.services.agent_runtime.legacy_availability import (
    LegacyRuntimeAvailability,
)
from app.services.conversation.authoritative_reader import (
    JournalConversationReader,
)
from app.services.conversation.contracts import ConversationReadRequest
from app.services.memory.version_contracts import (
    ForgetMemoryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
)
from app.services.memory.version_runtime import (
    execute_forget_memory,
    execute_remember_memory,
    execute_search_memory,
)
from app.services.tasks.contracts import TaskPlanDraft
from app.utils.turn_context import user_message_scope


logger = logging.getLogger(__name__)

_RETIRED_CHAT_MEMORY_WRITE_OPERATIONS = frozenset(
    {"remember_memory", "revise_memory"}
)
_LEGACY_CONTEXT_OPERATIONS = frozenset(
    {
        "process_memory_write_request",
        "recall_recent_conversation",
        "search_memory",
    }
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
        "remember_memory_v2",
        "search_memory_v2",
        "forget_memory_v2",
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
        "remember_memory_v2",
        "forget_memory_v2",
    }
)


class SystemRuntime:
    """The only component allowed to turn a plan into side effects/results."""

    def __init__(
        self,
        *,
        ledger: ExecutionLedger | None = None,
        external_runtime: Any | None = None,
        capability_registry: CapabilityRegistry | None = None,
        legacy_availability: LegacyRuntimeAvailability | None = None,
    ) -> None:
        self._ledger = ledger
        self._external_runtime = external_runtime
        self._capability_registry = (
            capability_registry or CapabilityRegistry()
        )
        self._legacy_availability = (
            legacy_availability or LegacyRuntimeAvailability.from_settings()
        )

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
                recovered = await self._recovered_receipt(
                    plan=plan,
                    action=action,
                    context=context,
                )
                if recovered is not None:
                    receipts.append(recovered)
                    continue
                dependency_failure = _dependency_failure(action, receipts)
                if dependency_failure:
                    receipt = ActionReceipt(
                        action_id=action.action_id,
                        capability=action.capability,
                        operation=action.operation,
                        status="skipped",
                        business_input=action.arguments,
                        error=dependency_failure,
                        admitted=False,
                        metadata={"dependency_gate": "failed"},
                    )
                    receipts.append(
                        await self._record_receipt(
                            plan=plan,
                            action=action,
                            context=context,
                            receipt=receipt,
                        )
                    )
                    continue

                admitted, reason = self._admit_action(
                    plan,
                    action,
                    policy,
                )
                if not admitted:
                    receipt = ActionReceipt(
                        action_id=action.action_id,
                        capability=action.capability,
                        operation=action.operation,
                        status="blocked",
                        business_input=action.arguments,
                        error=reason,
                        admitted=False,
                        metadata={"policy_gate": reason},
                    )
                    receipts.append(
                        await self._record_receipt(
                            plan=plan,
                            action=action,
                            context=context,
                            receipt=receipt,
                        )
                    )
                    continue

                receipt = await self._execute_action(
                    action,
                    context=context,
                    user_input=user_input,
                    previous=receipts,
                )
                receipts.append(
                    await self._record_receipt(
                        plan=plan,
                        action=action,
                        context=context,
                        receipt=receipt,
                    )
                )

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

    def _admit_action(
        self,
        plan: ActionPlan,
        action: PlannedAction,
        policy: Any | None,
    ) -> tuple[bool, str]:
        core_admission = (
            self._capability_registry.core_availability.operation_admission(
                action.operation
            )
        )
        if core_admission is not None and not core_admission[0]:
            return core_admission
        if (
            action.operation == "process_memory_write_request"
            and (
                self._capability_registry.core_availability.memory_write
                or not self._legacy_availability.memory_write_compat
            )
        ):
            return False, "legacy_memory_write_disabled_for_r6"
        admitted, reason = _admit_action(
            plan,
            action,
            policy,
            capability_registry=self._capability_registry,
        )
        if not admitted:
            return admitted, reason
        runtime = self._external_capability_runtime(action.operation)
        if runtime is None:
            return admitted, reason
        return runtime.admit(action.operation)

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

    async def _recovered_receipt(
        self,
        *,
        plan: ActionPlan,
        action: PlannedAction,
        context: ExecutionContext,
    ) -> ActionReceipt | None:
        if self._ledger is None:
            return None
        existing = await self._ledger.get(
            plan=plan,
            action=action,
            context=context,
        )
        if existing is None:
            return None
        metadata = dict(existing.metadata)
        metadata.update(
            {
                "recovered_from_ledger": True,
                "idempotency_key": action_idempotency_key(
                    plan=plan,
                    action=action,
                    context=context,
                ),
            }
        )
        return existing.model_copy(update={"metadata": metadata})

    async def _record_receipt(
        self,
        *,
        plan: ActionPlan,
        action: PlannedAction,
        context: ExecutionContext,
        receipt: ActionReceipt,
    ) -> ActionReceipt:
        metadata = dict(receipt.metadata)
        metadata["idempotency_key"] = action_idempotency_key(
            plan=plan,
            action=action,
            context=context,
        )
        identified = receipt.model_copy(update={"metadata": metadata})
        if self._ledger is None:
            return identified
        return await self._ledger.record(
            plan=plan,
            action=action,
            context=context,
            receipt=identified,
        )

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
                from app.services.agent_runtime.legacy_operations import (
                    process_memory_write_request,
                )

                output = await process_memory_write_request(
                    action,
                    context=context,
                    user_input=user_input,
                )
            elif action.operation == "recall_recent_conversation":
                from app.services.agent_runtime.legacy_operations import (
                    recall_conversation,
                )

                output = recall_conversation(
                    action,
                    context=context,
                )
            elif action.operation == "conversation_read":
                output = await _read_conversation(
                    action,
                    context=context,
                )
            elif action.operation == "remember_memory_v2":
                output = await execute_remember_memory(
                    action.arguments,
                    action_id=action.action_id,
                    context=context,
                    user_input=user_input,
                )
            elif action.operation == "search_memory_v2":
                output = await execute_search_memory(
                    action.arguments,
                    context=context,
                )
            elif action.operation == "forget_memory_v2":
                output = await execute_forget_memory(
                    action.arguments,
                    action_id=action.action_id,
                    context=context,
                    user_input=user_input,
                )
            elif action.operation == "create_task_v1":
                from app.services.tasks.runtime import execute_create_task

                output = await execute_create_task(
                    action.arguments,
                    context=context,
                    capability_registry=self._capability_registry,
                )
            elif action.operation == "plan_task_v1":
                from app.services.tasks.runtime import execute_plan_task

                output = await execute_plan_task(
                    action.arguments,
                    context=context,
                    capability_registry=self._capability_registry,
                )
            elif action.operation == "cancel_active_task_v1":
                from app.services.tasks.runtime import (
                    execute_cancel_active_task,
                )

                output = await execute_cancel_active_task(
                    action.arguments,
                    context=context,
                )
            elif action.operation == "search_memory":
                from app.services.agent_runtime.legacy_operations import (
                    search_memory,
                )

                output = await search_memory(action, context=context)
            elif (
                external_runtime := self._external_capability_runtime(
                    action.operation
                )
            ) is not None:
                output = await external_runtime.execute(
                    action.operation,
                    action.arguments,
                    context=context,
                    previous=previous,
                )
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


async def _read_conversation(
    action: PlannedAction,
    *,
    context: ExecutionContext,
) -> dict[str, Any]:
    request = ConversationReadRequest.model_validate(action.arguments)
    if context.thread_id is None:
        raise ValueError("conversation_read requires a conversation thread")
    database = get_database()
    async with database.session() as session:
        result = await JournalConversationReader().read(
            session,
            user_id=context.user_id,
            thread_id=context.thread_id,
            exclude_request_id=context.request_id,
            request=request,
        )
    return result.model_dump(mode="json")


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
    if operation in {"create_task_v1", "plan_task_v1"}:
        return ["user_id", "thread_id", "origin_request_id"]
    if operation == "cancel_active_task_v1":
        return ["user_id", "thread_id"]
    result: list[str] = []
    if operation in _USER_ID_OPERATIONS:
        result.append("user_id")
    if operation in _THREAD_ID_OPERATIONS and context.thread_id is not None:
        result.append("thread_id")
    return result


def _admit_action(
    plan: ActionPlan,
    action: PlannedAction,
    policy: Any | None,
    *,
    capability_registry: CapabilityRegistry,
) -> tuple[bool, str]:
    if action.operation in set(plan.forbidden_operations):
        return False, "operation_forbidden_by_action_plan"
    if (
        action.operation in _LEGACY_CONTEXT_OPERATIONS
        and plan.source != "routing_decision"
    ):
        return False, "legacy_operation_requires_routing_plan"
    if action.operation in _RETIRED_CHAT_MEMORY_WRITE_OPERATIONS:
        return False, "chat_memory_write_requires_precommit_pipeline"
    if plan.policy and (
        policy is None
        or action.operation not in set(policy.allowed_tools)
    ):
        return False, "operation_not_authorized_by_routing_policy"

    flag = {
        "web_search": "can_use_web_search",
        "acquire_research_sources": "can_use_web_search",
        "search_books": "can_search_books",
        "get_recommendation_history": "can_view_recommendation_history",
        "start_research": "can_start_research",
    }.get(action.operation)
    if flag and (
        policy is None or not bool(getattr(policy, flag, False))
    ):
        return False, f"turn_policy_{flag}_false"

    if action.operation in _LEGACY_CONTEXT_OPERATIONS:
        from app.services.agent_runtime.legacy_admission import (
            admit_legacy_context_operation,
        )

        return admit_legacy_context_operation(plan, action)
    if action.operation == "conversation_read":
        return True, "agent_core_conversation_read"
    if action.operation == "remember_memory_v2":
        try:
            request = RememberMemoryRequest.model_validate(action.arguments)
        except Exception:
            return False, "versioned_memory_request_invalid"
        goal = " ".join(str(plan.goal or "").split()).strip().casefold()
        if any(
            assertion.evidence_quote.casefold() not in goal
            for assertion in request.assertions
        ):
            return False, "memory_evidence_must_be_user_authored"
        return True, "versioned_memory_precommit"
    if action.operation == "search_memory_v2":
        try:
            SearchMemoryRequest.model_validate(action.arguments)
        except Exception:
            return False, "versioned_memory_search_invalid"
        return True, "versioned_memory_current_head_read"
    if action.operation == "forget_memory_v2":
        try:
            request = ForgetMemoryRequest.model_validate(action.arguments)
        except Exception:
            return False, "versioned_memory_forget_invalid"
        goal = " ".join(str(plan.goal or "").split()).strip().casefold()
        if any(
            target.evidence_quote.casefold() not in goal
            for target in request.targets
        ):
            return False, "memory_evidence_must_be_user_authored"
        return True, "versioned_memory_tombstone"
    if action.operation == "create_task_v1":
        if plan.source != "controller_proposal":
            return False, "task_creation_requires_controller_proposal"
        if set(action.arguments) != {"draft"}:
            return False, "task_creation_arguments_invalid"
        try:
            from app.services.tasks.draft_validator import (
                TaskPlanDraftValidator,
            )

            draft = TaskPlanDraft.model_validate(action.arguments["draft"])
            TaskPlanDraftValidator(capability_registry).validate(draft)
        except Exception:
            return False, "task_plan_draft_invalid"
        return True, "task_creation_v1"
    if action.operation == "plan_task_v1":
        if plan.source not in {
            "controller_proposal",
            "shadow_validation",
        }:
            return False, "task_planning_requires_controller_proposal"
        if set(action.arguments) != {"draft"}:
            return False, "task_planning_arguments_invalid"
        try:
            from app.services.tasks.draft_validator import (
                TaskPlanDraftValidator,
            )

            draft = TaskPlanDraft.model_validate(action.arguments["draft"])
            TaskPlanDraftValidator(capability_registry).validate(draft)
        except Exception:
            return False, "task_plan_draft_invalid"
        return True, "task_planning_v1"
    if action.operation == "cancel_active_task_v1":
        if plan.source != "controller_proposal":
            return False, "task_cancellation_requires_controller_proposal"
        if set(action.arguments) - {"reason"}:
            return False, "task_cancellation_arguments_invalid"
        if len(str(action.arguments.get("reason") or "")) > 1_000:
            return False, "task_cancellation_arguments_invalid"
        return True, "task_cancellation_v1"
    return True, "admitted"


def _policy_from_plan(plan: ActionPlan, user_message: str) -> Any | None:
    if plan.source != "routing_decision":
        return None
    from app.services.book_intent import TurnPolicy, build_turn_policy

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
    if status in {"clarification_required", "waiting"}:
        return "waiting", error
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
    if "waiting" in statuses and "failed" not in statuses:
        return "waiting"
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
