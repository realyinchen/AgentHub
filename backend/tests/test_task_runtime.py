from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent_runtime import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlannedAction,
    SystemRuntime,
    action_idempotency_key,
)
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.tasks import (
    TaskPlanDraft,
    TaskPlanStepDraft,
    TaskPlanVersion,
)
from app.services.tasks.plan_compiler import TaskPlanCompiler
from app.services.tasks.draft_validator import TaskPlanDraftValidator
from app.models.task import ActionExecutionReceiptRecord
from app.services.tasks.execution_ledger import (
    ExecutionReceiptConflict,
    _assert_identity,
)


def _enabled_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        core_availability=CoreCapabilityAvailability.all_enabled()
    )


class TaskPlanContractTests(unittest.TestCase):
    def test_model_draft_rejects_nested_system_fields(self) -> None:
        with self.assertRaises(ValidationError):
            TaskPlanDraft(
                goal="读取历史",
                steps=[
                    TaskPlanStepDraft(
                        step_key="read_history",
                        title="读取",
                        capability="conversation_read",
                        arguments={
                            "target": "exchange",
                            "nested": {"thread_id": str(uuid.uuid4())},
                        },
                    )
                ],
            )

    def test_dependency_cycle_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "dependency cycle"):
            TaskPlanDraft(
                goal="循环计划",
                steps=[
                    TaskPlanStepDraft(
                        step_key="first",
                        title="第一步",
                        capability="search_memory",
                        depends_on=["second"],
                    ),
                    TaskPlanStepDraft(
                        step_key="second",
                        title="第二步",
                        capability="search_memory",
                        depends_on=["first"],
                    ),
                ],
            )

    def test_draft_validator_rejects_unknown_capability(self) -> None:
        draft = TaskPlanDraft(
            goal="执行未知能力",
            steps=[
                TaskPlanStepDraft(
                    step_key="unknown",
                    title="未知",
                    capability="unknown_capability",
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "unknown capability"):
            TaskPlanDraftValidator(_enabled_registry()).validate(draft)

    def test_draft_validator_rejects_invalid_capability_arguments(self) -> None:
        draft = TaskPlanDraft(
            goal="读取历史",
            steps=[
                TaskPlanStepDraft(
                    step_key="read",
                    title="读取",
                    capability="conversation_read",
                    arguments={"target": "not-a-valid-target"},
                )
            ],
        )
        with self.assertRaises(ValidationError):
            TaskPlanDraftValidator(_enabled_registry()).validate(draft)

    def test_compiler_emits_only_ready_steps_with_stable_action_id(self) -> None:
        task_id = uuid.uuid4()
        version_id = uuid.uuid4()
        version = TaskPlanVersion(
            id=version_id,
            task_id=task_id,
            version_no=1,
            draft=TaskPlanDraft(
                goal="先查记忆，再读对话",
                steps=[
                    TaskPlanStepDraft(
                        step_key="search",
                        title="查记忆",
                        capability="search_memory",
                        arguments={"query": "name", "predicate": ""},
                    ),
                    TaskPlanStepDraft(
                        step_key="read",
                        title="读对话",
                        capability="conversation_read",
                        arguments={
                            "target": "exchange",
                            "selection": "latest",
                            "count": 1,
                        },
                        depends_on=["search"],
                    ),
                ],
            ),
            source="controller",
            created_at=datetime.now(timezone.utc),
        )
        compiler = TaskPlanCompiler(registry=_enabled_registry())
        first = compiler.compile_next(version, completed_step_keys=set())
        repeated = compiler.compile_next(version, completed_step_keys=set())
        self.assertEqual(first.status, "ready")
        self.assertEqual(first.ready_step_keys, ["search"])
        self.assertEqual(first.plan.source, "workflow_resume")
        self.assertEqual(first.plan.actions[0].operation, "search_memory_v2")
        self.assertEqual(
            first.plan.actions[0].action_id,
            repeated.plan.actions[0].action_id,
        )
        self.assertEqual(first.plan.plan_id, repeated.plan.plan_id)
        second = compiler.compile_next(
            version,
            completed_step_keys={"search"},
        )
        self.assertEqual(second.ready_step_keys, ["read"])


class _MemoryLedger:
    def __init__(self, *, fail_record: bool = False) -> None:
        self.receipts = {}
        self.fail_record = fail_record

    async def get(self, *, plan, action, context):
        return self.receipts.get(
            action_idempotency_key(
                plan=plan,
                action=action,
                context=context,
            )
        )

    async def record(self, *, plan, action, context, receipt):
        if self.fail_record:
            raise RuntimeError("ledger unavailable")
        key = action_idempotency_key(
            plan=plan,
            action=action,
            context=context,
        )
        self.receipts.setdefault(key, receipt)
        return self.receipts[key]


class _CountingRuntime(SystemRuntime):
    def __init__(self, ledger) -> None:
        super().__init__(
            ledger=ledger,
            capability_registry=_enabled_registry(),
        )
        self.execution_count = 0

    async def _execute_action(self, action, *, context, user_input, previous):
        self.execution_count += 1
        return ActionReceipt(
            action_id=action.action_id,
            capability=action.capability,
            operation=action.operation,
            status="completed",
            output={"value": "done"},
            admitted=True,
        )


class _WaitingRuntime(SystemRuntime):
    async def _execute_action(self, action, *, context, user_input, previous):
        return ActionReceipt(
            action_id=action.action_id,
            capability=action.capability,
            operation=action.operation,
            status="waiting",
            output={
                "status": "clarification_required",
                "clarification_question": "请补充任务所需信息。",
            },
            admitted=True,
        )


class RuntimeLedgerTests(unittest.IsolatedAsyncioTestCase):
    def _plan(self) -> ActionPlan:
        return ActionPlan(
            plan_id="plan-stable",
            source="workflow_resume",
            route_type="slow_path",
            intent="task_execution",
            goal="读取上一轮",
            actions=[
                PlannedAction(
                    action_id="action-stable",
                    capability="conversation",
                    operation="conversation_read",
                    arguments={
                        "target": "exchange",
                        "selection": "latest",
                        "count": 1,
                    },
                )
            ],
        )

    def _context(self) -> ExecutionContext:
        return ExecutionContext(
            user_id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            request_id="task-request",
            task_id=uuid.uuid4(),
            plan_version_id=uuid.uuid4(),
            lease_owner="worker-1",
        )

    async def test_recovery_reuses_receipt_without_reexecuting_action(self) -> None:
        ledger = _MemoryLedger()
        runtime = _CountingRuntime(ledger)
        plan = self._plan()
        context = self._context()

        first = await runtime.execute(plan, context=context)
        second = await runtime.execute(plan, context=context)

        self.assertEqual(runtime.execution_count, 1)
        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "completed")
        self.assertTrue(
            second.actions[0].metadata["recovered_from_ledger"]
        )

    async def test_receipt_persistence_failure_stops_runtime(self) -> None:
        runtime = _CountingRuntime(_MemoryLedger(fail_record=True))
        with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
            await runtime.execute(self._plan(), context=self._context())
        self.assertEqual(runtime.execution_count, 1)

    async def test_runtime_revalidates_task_draft_before_persistence(
        self,
    ) -> None:
        plan = ActionPlan(
            source="controller_proposal",
            route_type="slow_path",
            intent="create_task",
            goal="创建未知任务",
            actions=[
                PlannedAction(
                    action_id="create-task",
                    capability="task",
                    operation="create_task_v1",
                    arguments={
                        "draft": TaskPlanDraft(
                            goal="未知任务",
                            steps=[
                                TaskPlanStepDraft(
                                    step_key="unknown",
                                    title="未知",
                                    capability="unknown_capability",
                                )
                            ],
                        ).model_dump(mode="json")
                    },
                )
            ],
        )
        receipt = await SystemRuntime(
            capability_registry=_enabled_registry()
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid.uuid4(),
                thread_id=uuid.uuid4(),
                request_id="invalid-task",
            ),
        )
        self.assertEqual(receipt.status, "blocked")
        self.assertEqual(
            receipt.actions[0].error,
            "task_plan_draft_invalid",
        )

    async def test_waiting_action_never_marks_plan_completed(self) -> None:
        receipt = await _WaitingRuntime(
            capability_registry=_enabled_registry()
        ).execute(
            self._plan(),
            context=self._context(),
        )
        self.assertEqual(receipt.status, "waiting")
        self.assertEqual(receipt.actions[0].status, "waiting")


class ExecutionReceiptIdentityTests(unittest.TestCase):
    def _record(
        self,
        *,
        plan: ActionPlan,
        action: PlannedAction,
        context: ExecutionContext,
    ) -> ActionExecutionReceiptRecord:
        receipt = ActionReceipt(
            action_id=action.action_id,
            capability=action.capability,
            operation=action.operation,
            status="completed",
            business_input=action.arguments,
            admitted=True,
        )
        return ActionExecutionReceiptRecord(
            idempotency_key=action_idempotency_key(
                plan=plan,
                action=action,
                context=context,
            ),
            task_id=context.task_id,
            plan_version_id=context.plan_version_id,
            plan_id=plan.plan_id,
            action_id=action.action_id,
            request_id=context.request_id,
            capability=action.capability,
            operation=action.operation,
            status=receipt.status,
            receipt_json=receipt.model_dump(mode="json"),
        )

    def test_task_receipt_identity_ignores_recovery_request_id(self) -> None:
        plan = RuntimeLedgerTests()._plan()
        original = RuntimeLedgerTests()._context()
        record = self._record(
            plan=plan,
            action=plan.actions[0],
            context=original,
        )
        recovered = original.model_copy(
            update={"request_id": "task-recovery-new-request"}
        )

        _assert_identity(record, plan, plan.actions[0], recovered)

    def test_turn_receipt_identity_requires_same_request_id(self) -> None:
        plan = RuntimeLedgerTests()._plan().model_copy(
            update={"source": "controller_proposal"}
        )
        original = RuntimeLedgerTests()._context().model_copy(
            update={
                "task_id": None,
                "plan_version_id": None,
                "lease_owner": None,
            }
        )
        record = self._record(
            plan=plan,
            action=plan.actions[0],
            context=original,
        )
        different = original.model_copy(
            update={"request_id": "another-turn-request"}
        )

        with self.assertRaises(ExecutionReceiptConflict):
            _assert_identity(record, plan, plan.actions[0], different)


if __name__ == "__main__":
    unittest.main()
