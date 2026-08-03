"""Verify atomic plan create/revise/reuse, legal resume, and cancellation."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_runtime import (
    ActionReceipt,
    ExecutionContext,
    SystemRuntime,
)
from app.services.tasks.contracts import (
    CancellationReceipt,
    TaskPlanDraft,
    TaskPlanMutationReceipt,
    TaskPlanStepDraft,
)
from app.services.tasks.execution_ledger import PostgresExecutionLedger
from app.services.tasks.repository import TaskLeaseError, TaskRepository
from app.services.tasks.resume_factory import TaskResumeCommandFactory
from app.services.tasks.runner_contracts import TaskResumeCommand, TaskRunCommand
from scripts.agent_core_verifier_fixtures import (
    FIXTURE_REGISTRY_NAME,
    build_verifier_registry,
    build_verifier_harness,
    build_verifier_task_runner,
)
from scripts.init_database import _init_postgres


class _WaitingRuntime(SystemRuntime):
    def __init__(self) -> None:
        super().__init__(
            ledger=PostgresExecutionLedger(),
            capability_registry=build_verifier_registry(),
        )
        self.execution_count = 0

    async def _execute_action(self, action, *, context, user_input, previous):
        self.execution_count += 1
        return ActionReceipt(
            action_id=action.action_id,
            capability=action.capability,
            operation=action.operation,
            status="waiting",
            business_input=action.arguments,
            output={
                "status": "clarification_required",
                "clarification_question": "Please provide the missing detail.",
            },
            admitted=True,
        )


class _CompletedRuntime(SystemRuntime):
    def __init__(self) -> None:
        super().__init__(
            ledger=PostgresExecutionLedger(),
            capability_registry=build_verifier_registry(),
        )
        self.execution_count = 0

    async def _execute_action(self, action, *, context, user_input, previous):
        self.execution_count += 1
        return ActionReceipt(
            action_id=action.action_id,
            capability=action.capability,
            operation=action.operation,
            status="completed",
            business_input=action.arguments,
            output={"status": "completed"},
            admitted=True,
        )


def _draft(*, count: int = 1) -> TaskPlanDraft:
    return TaskPlanDraft(
        goal="Read prior exchanges",
        steps=[
            TaskPlanStepDraft(
                step_key="read",
                title="Read prior exchanges",
                capability="conversation_read",
                arguments={
                    "target": "exchange",
                    "selection": "last_n",
                    "count": count,
                },
            )
        ],
    )


def _proposal(*, count: int = 1) -> ControllerOutput:
    return ControllerOutput(
        mode="task_plan_proposal",
        task_plan_proposal=_draft(count=count),
    )


def _mutation(result) -> TaskPlanMutationReceipt:
    if result.receipt is None or len(result.receipt.actions) != 1:
        raise AssertionError("task plan mutation lacks one action receipt")
    action = result.receipt.actions[0]
    if action.operation != "plan_task_v1":
        raise AssertionError("task planning bypassed plan_task_v1")
    if action.metadata.get("runtime_dispatch") != "system_runtime":
        raise AssertionError("task planning bypassed SystemRuntime")
    return TaskPlanMutationReceipt.model_validate(action.output)


async def _add_thread(user_id: uuid.UUID) -> uuid.UUID:
    thread_id = uuid.uuid4()
    database = get_database()
    async with database.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO public.conversations (thread_id, user_id, title)
                VALUES (:thread_id, :user_id, 'Task Plan Coordination Verify')
                """
            ),
            {"thread_id": thread_id, "user_id": user_id},
        )
    return thread_id


async def _version_rows(task_id: uuid.UUID) -> list[tuple[int, dict]]:
    database = get_database()
    async with database.session() as session:
        result = await session.execute(
            text(
                """
                SELECT version_no, plan_json
                FROM public.task_plan_versions
                WHERE task_id = :task_id
                ORDER BY version_no
                """
            ),
            {"task_id": task_id},
        )
        return [(int(row.version_no), dict(row.plan_json)) for row in result]


async def _run() -> None:
    _init_postgres()
    await init_database_connection()
    database = get_database()
    repository = TaskRepository()
    harness = build_verifier_harness()
    user_id = uuid.uuid4()
    try:
        async with database.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.users (id, display_name, is_mock_user)
                    VALUES (:user_id, 'Task Plan Coordination Verify', true)
                    """
                ),
                {"user_id": user_id},
            )

        revision_thread = await _add_thread(user_id)
        create_context = ExecutionContext(
            user_id=user_id,
            thread_id=revision_thread,
            request_id=f"create-{uuid.uuid4()}",
        )
        created_result = await harness.run(
            _proposal(count=1),
            goal="Create a durable task",
            context=create_context,
        )
        created = _mutation(created_result)
        if created.mutation != "created" or created.task_id is None:
            raise AssertionError("initial plan did not create one task")

        waiting_runtime = _WaitingRuntime()
        waiting = await build_verifier_task_runner(
            repository=repository,
            runtime=waiting_runtime,
        ).run(
            TaskRunCommand(
                task_id=created.task_id,
                user_id=user_id,
                thread_id=revision_thread,
                request_id=f"wait-{uuid.uuid4()}",
                lease_owner="r3-wait-worker",
            )
        )
        if waiting.status != "waiting":
            raise AssertionError("fixture task did not enter waiting")

        same_version = TaskResumeCommand(
            task_id=created.task_id,
            plan_version_id=created.plan_version_id,
            expected_state_version=waiting.task_state.state_version,
            user_id=user_id,
            thread_id=revision_thread,
            request_id=f"illegal-resume-{uuid.uuid4()}",
            lease_owner="r3-illegal-resume",
        )
        try:
            await build_verifier_task_runner(repository=repository).resume(
                same_version
            )
        except TaskLeaseError:
            pass
        else:
            raise AssertionError("same plan version resumed a waiting task")

        revision_request = f"revision-{uuid.uuid4()}"
        revision_context = ExecutionContext(
            user_id=user_id,
            thread_id=revision_thread,
            request_id=revision_request,
        )
        first_revision, replay_revision = await asyncio.gather(
            harness.run(
                _proposal(count=2),
                goal="Revise the durable task after clarification",
                context=revision_context,
            ),
            harness.run(
                _proposal(count=2),
                goal="Revise the durable task after clarification",
                context=revision_context,
            ),
        )
        revision_receipts = [
            _mutation(first_revision),
            _mutation(replay_revision),
        ]
        if sorted(item.mutation for item in revision_receipts) != [
            "reused",
            "revised",
        ]:
            raise AssertionError(
                "concurrent revision was not append-once/reuse-once"
            )
        if len({item.plan_version_id for item in revision_receipts}) != 1:
            raise AssertionError("revision replay returned different versions")
        if not all(item.resume_required for item in revision_receipts):
            raise AssertionError("persisted waiting revision did not authorize resume")

        rows = await _version_rows(created.task_id)
        if [row[0] for row in rows] != [1, 2]:
            raise AssertionError("revision did not append exactly one v2")
        if rows[0][1] != _draft(count=1).model_dump(mode="json"):
            raise AssertionError("revision mutated immutable v1")

        conflict = _mutation(
            await harness.run(
                _proposal(count=3),
                goal="Conflicting replay",
                context=revision_context,
            )
        )
        if (
            conflict.status != "blocked"
            or conflict.reason != "origin_request_conflict"
        ):
            raise AssertionError("conflicting revision replay was not blocked")
        if len(await _version_rows(created.task_id)) != 2:
            raise AssertionError("conflicting replay appended a version")

        revised = next(
            item
            for item in revision_receipts
            if item.mutation == "revised"
        )
        resume_command = TaskResumeCommandFactory().create(
            revised,
            context=ExecutionContext(
                user_id=user_id,
                thread_id=revision_thread,
                request_id=f"resume-{uuid.uuid4()}",
            ),
            lease_owner="r3-resume-worker",
        )
        completed_runtime = _CompletedRuntime()
        resumed = await build_verifier_task_runner(
            repository=repository,
            runtime=completed_runtime,
        ).resume(resume_command)
        if resumed.status != "completed":
            raise AssertionError("new plan version did not resume to completion")
        if completed_runtime.execution_count != 1:
            raise AssertionError("resumed version executed an unexpected count")

        running_thread = await _add_thread(user_id)
        running_create = _mutation(
            await harness.run(
                _proposal(),
                goal="Create a running task",
                context=ExecutionContext(
                    user_id=user_id,
                    thread_id=running_thread,
                    request_id=f"running-create-{uuid.uuid4()}",
                ),
            )
        )
        async with database.session() as session:
            await repository.claim_start_or_recover(
                session,
                running_create.task_id,
                user_id=user_id,
                thread_id=running_thread,
                owner="r3-running-worker",
            )
        running_revision = _mutation(
            await harness.run(
                _proposal(count=2),
                goal="Revise while running",
                context=ExecutionContext(
                    user_id=user_id,
                    thread_id=running_thread,
                    request_id=f"running-revision-{uuid.uuid4()}",
                ),
            )
        )
        if (
            running_revision.status != "blocked"
            or running_revision.reason != "active_task_running"
        ):
            raise AssertionError("running task revision was not fenced")

        cancel_thread = await _add_thread(user_id)
        cancel_created = _mutation(
            await harness.run(
                _proposal(),
                goal="Create a cancellable task",
                context=ExecutionContext(
                    user_id=user_id,
                    thread_id=cancel_thread,
                    request_id=f"cancel-create-{uuid.uuid4()}",
                ),
            )
        )
        cancel_result = await harness.run(
            ControllerOutput(
                mode="capability_proposals",
                tool_calls=[
                    ControllerToolCall(
                        call_id="cancel-active",
                        name="cancel_active_task",
                        arguments={"reason": "User changed direction"},
                    )
                ],
            ),
            goal="Cancel the active task",
            context=ExecutionContext(
                user_id=user_id,
                thread_id=cancel_thread,
                request_id=f"cancel-{uuid.uuid4()}",
            ),
        )
        if cancel_result.receipt is None:
            raise AssertionError("cancellation produced no receipt")
        cancel_action = cancel_result.receipt.actions[0]
        cancellation = CancellationReceipt.model_validate(cancel_action.output)
        if not cancellation.cancelled:
            raise AssertionError("active task was not cancelled")
        async with database.session() as session:
            cancelled_state = await repository.get(
                session,
                cancel_created.task_id,
                user_id=user_id,
                thread_id=cancel_thread,
            )
        if cancelled_state.status != "cancelled":
            raise AssertionError("cancellation receipt did not match TaskState")

        print("task plan coordination verification passed")
        print(f"fixture_registry={FIXTURE_REGISTRY_NAME}")
        print("plan_task_model_tools=1")
        print("concurrent_revision_appends=1")
        print("concurrent_revision_reuses=1")
        print("same_version_resume=blocked")
        print("new_version_resume=completed")
        print("running_revision=blocked")
        print("conflicting_revision_replay=blocked")
        print("cancel_without_task_id=completed")
        print("immutable_v1=preserved")
    finally:
        async with database.session() as session:
            await session.execute(
                text("DELETE FROM public.users WHERE id = :user_id"),
                {"user_id": user_id},
            )
        await dispose_database()


if __name__ == "__main__":
    asyncio.run(_run())
