from __future__ import annotations

import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.services.agent_core.capabilities import (
    CancelActiveTaskInput,
    CapabilityRegistry,
)
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_runtime.contracts import (
    ActionReceipt,
    ExecutionContext,
    PlanReceipt,
)
from app.services.tasks.contracts import (
    TaskPlanDraft,
    TaskPlanMutationReceipt,
    TaskPlanStepDraft,
)
from app.services.tasks.planning_compiler import TaskPlanningCompiler
from app.services.tasks.resume_factory import TaskResumeCommandFactory
from app.services.tasks.resume_dispatcher import TaskResumeDispatcher


def _draft() -> TaskPlanDraft:
    return TaskPlanDraft(
        goal="Read the prior exchange",
        steps=[
            TaskPlanStepDraft(
                step_key="read",
                title="Read the prior exchange",
                capability="conversation_read",
                arguments={
                    "target": "exchange",
                    "selection": "latest",
                    "count": 1,
                },
            )
        ],
    )


def _enabled_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        core_availability=CoreCapabilityAvailability.all_enabled()
    )


class TaskPlanningCompilerTests(unittest.TestCase):
    def test_unified_plan_action_contains_no_system_identity(self) -> None:
        from app.services.tasks.draft_validator import TaskPlanDraftValidator

        plan = TaskPlanningCompiler().compile(
            TaskPlanDraftValidator(_enabled_registry()).validate(_draft()),
            goal="Continue the durable task",
        )

        self.assertEqual(plan.actions[0].operation, "plan_task_v1")
        self.assertEqual(set(plan.actions[0].arguments), {"draft"})
        serialized = str(plan.actions[0].arguments)
        for forbidden in (
            "task_id",
            "thread_id",
            "user_id",
            "state_version",
            "plan_version_id",
            "origin_request_id",
        ):
            self.assertNotIn(forbidden, serialized)


class TaskPlanMutationReceiptTests(unittest.TestCase):
    def test_completed_revision_requires_system_receipt_identity(self) -> None:
        receipt = TaskPlanMutationReceipt(
            status="completed",
            mutation="revised",
            task_id=uuid4(),
            plan_version_id=uuid4(),
            version_no=2,
            state_version=5,
            step_count=1,
            resume_required=True,
        )
        self.assertTrue(receipt.resume_required)

    def test_blocked_mutation_cannot_expose_internal_identity(self) -> None:
        with self.assertRaises(ValidationError):
            TaskPlanMutationReceipt(
                status="blocked",
                mutation="blocked",
                task_id=uuid4(),
                step_count=1,
                reason="active_task_running",
            )


class TaskResumeCommandFactoryTests(unittest.TestCase):
    def test_only_successful_revision_can_create_resume_command(self) -> None:
        context = ExecutionContext(
            user_id=uuid4(),
            thread_id=uuid4(),
            request_id="resume-request",
        )
        receipt = TaskPlanMutationReceipt(
            status="completed",
            mutation="revised",
            task_id=uuid4(),
            plan_version_id=uuid4(),
            version_no=2,
            state_version=7,
            step_count=1,
            resume_required=True,
        )

        command = TaskResumeCommandFactory().create(
            receipt,
            context=context,
            lease_owner="worker-r3",
        )

        self.assertEqual(command.task_id, receipt.task_id)
        self.assertEqual(command.plan_version_id, receipt.plan_version_id)
        self.assertEqual(command.expected_state_version, receipt.state_version)

    def test_created_task_does_not_authorize_resume(self) -> None:
        context = ExecutionContext(
            user_id=uuid4(),
            thread_id=uuid4(),
            request_id="create-request",
        )
        receipt = TaskPlanMutationReceipt(
            status="completed",
            mutation="created",
            task_id=uuid4(),
            plan_version_id=uuid4(),
            version_no=1,
            state_version=1,
            step_count=1,
            resume_required=False,
        )
        with self.assertRaisesRegex(ValueError, "revision"):
            TaskResumeCommandFactory().create(
                receipt,
                context=context,
                lease_owner="worker-r3",
            )


class CancelActiveTaskContractTests(unittest.TestCase):
    def test_model_schema_contains_no_task_identity(self) -> None:
        schema = str(CancelActiveTaskInput.model_json_schema())
        self.assertIn("reason", schema)
        for forbidden in (
            "task_id",
            "plan_version_id",
            "state_version",
            "thread_id",
            "user_id",
        ):
            self.assertNotIn(forbidden, schema)


class TaskResumeDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_feature_gate_prevents_resume_dispatch(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self.calls = 0

            async def resume(self, command):
                self.calls += 1
                raise AssertionError("disabled dispatcher called runner")

        runner = _Runner()
        mutation = TaskPlanMutationReceipt(
            status="completed",
            mutation="revised",
            task_id=uuid4(),
            plan_version_id=uuid4(),
            version_no=2,
            state_version=7,
            step_count=1,
            resume_required=True,
        )
        receipt = PlanReceipt(
            plan_id="plan-task",
            request_id="resume-request",
            route_type="slow_path",
            intent="plan_task",
            status="completed",
            actions=[
                ActionReceipt(
                    action_id="plan-task-v1",
                    capability="task",
                    operation="plan_task_v1",
                    status="completed",
                    output=mutation.model_dump(mode="json"),
                    admitted=True,
                )
            ],
        )
        result = await TaskResumeDispatcher(
            runner=runner,  # type: ignore[arg-type]
        ).dispatch(
            receipt,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="resume-request",
            ),
            enabled=False,
        )

        self.assertIsNone(result)
        self.assertEqual(runner.calls, 0)


if __name__ == "__main__":
    unittest.main()
