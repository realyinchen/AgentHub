"""Verify TaskRunner waiting, bounded yield, and non-resume semantics."""

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
from app.services.agent_runtime import ActionReceipt, SystemRuntime
from app.services.tasks import (
    TaskLeaseError,
    TaskPlanDraft,
    TaskPlanStepDraft,
    TaskRepository,
)
from app.services.tasks.execution_ledger import PostgresExecutionLedger
from app.services.tasks.runner_contracts import TaskRunCommand
from scripts.agent_core_verifier_fixtures import (
    FIXTURE_REGISTRY_NAME,
    build_task_plan_validator,
    build_verifier_registry,
    build_verifier_task_runner,
)
from scripts.init_database import _init_postgres


class _CountingRuntime(SystemRuntime):
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
                "clarification_question": "请补充任务所需信息。",
            },
            admitted=True,
        )


class _FailedRuntime(SystemRuntime):
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
            status="failed",
            business_input=action.arguments,
            error="fixture_failure",
            admitted=True,
        )


async def _create_task(
    *,
    repository: TaskRepository,
    user_id,
    thread_id,
    draft: TaskPlanDraft,
):
    database = get_database()
    async with database.session() as session:
        return await repository.create_v1(
            session,
            user_id=user_id,
            thread_id=thread_id,
            origin_request_id=f"task-runner-{uuid.uuid4()}",
            validated=build_task_plan_validator().validate(draft),
        )


async def _run() -> None:
    _init_postgres()
    await init_database_connection()
    database = get_database()
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    repository = TaskRepository()
    try:
        async with database.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.users (id, display_name, is_mock_user)
                    VALUES (:user_id, 'Task Runner Verify', true)
                    """
                ),
                {"user_id": user_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO public.conversations (thread_id, user_id, title)
                    VALUES (:thread_id, :user_id, 'Task Runner Verify')
                    """
                ),
                {"thread_id": thread_id, "user_id": user_id},
            )

        waiting_created = await _create_task(
            repository=repository,
            user_id=user_id,
            thread_id=thread_id,
            draft=TaskPlanDraft(
                goal="等待澄清",
                steps=[
                    TaskPlanStepDraft(
                        step_key="read",
                        title="读取历史",
                        capability="conversation_read",
                        arguments={
                            "target": "exchange",
                            "selection": "latest",
                            "count": 1,
                        },
                    )
                ],
            ),
        )
        waiting_runtime = _WaitingRuntime()
        waiting = await build_verifier_task_runner(
            repository=repository,
            runtime=waiting_runtime,
        ).run(
            TaskRunCommand(
                task_id=waiting_created.state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                request_id="waiting-first",
                lease_owner="waiting-worker",
            )
        )
        if waiting.status != "waiting":
            raise AssertionError("waiting receipt did not pause the task")
        if waiting_runtime.execution_count != 1:
            raise AssertionError("waiting action execution count is wrong")
        if waiting.task_state.recovery_cursor != 1:
            raise AssertionError("waiting receipt was not projected once")
        if waiting.task_state.completed_receipt_refs:
            raise AssertionError("waiting receipt was marked completed")
        if len(waiting.task_state.projected_receipt_refs) != 1:
            raise AssertionError("waiting receipt projection is missing")
        if waiting.task_state.lease_owner is not None:
            raise AssertionError("waiting task retained its lease")
        if waiting.waiting_question != "请补充任务所需信息。":
            raise AssertionError("waiting clarification was not preserved")

        forbidden_runtime = _CountingRuntime()
        replay = await build_verifier_task_runner(
            repository=repository,
            runtime=forbidden_runtime,
        ).run(
            TaskRunCommand(
                task_id=waiting_created.state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                request_id="waiting-replay",
                lease_owner="another-worker",
            )
        )
        if replay.status != "waiting" or forbidden_runtime.execution_count != 0:
            raise AssertionError("ordinary TaskRunCommand resumed waiting task")
        try:
            async with database.session() as session:
                await repository.claim_start_or_recover(
                    session,
                    waiting_created.state.task_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    owner="illegal-resume",
                )
        except TaskLeaseError:
            pass
        else:
            raise AssertionError("waiting task was claimed without a new plan")

        failed_created = await _create_task(
            repository=repository,
            user_id=user_id,
            thread_id=thread_id,
            draft=TaskPlanDraft(
                goal="失败后暂停",
                steps=[
                    TaskPlanStepDraft(
                        step_key="read",
                        title="读取历史",
                        capability="conversation_read",
                        arguments={
                            "target": "exchange",
                            "selection": "latest",
                            "count": 1,
                        },
                    )
                ],
            ),
        )
        failed_runtime = _FailedRuntime()
        failed = await build_verifier_task_runner(
            repository=repository,
            runtime=failed_runtime,
        ).run(
            TaskRunCommand(
                task_id=failed_created.state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                request_id="failed-first",
                lease_owner="failed-worker",
            )
        )
        if failed.status != "failed":
            raise AssertionError("failed receipt did not fail the task")
        if failed_runtime.execution_count != 1:
            raise AssertionError("failed action execution count is wrong")
        if failed.task_state.recovery_cursor != 1:
            raise AssertionError("failed receipt was not projected")
        if failed.task_state.completed_receipt_refs:
            raise AssertionError("failed receipt was marked completed")
        if failed.task_state.terminal_error is None:
            raise AssertionError("failed task lacks a typed error projection")
        if failed.task_state.lease_owner is not None:
            raise AssertionError("failed task retained its lease")

        failed_replay_runtime = _CountingRuntime()
        failed_replay = await build_verifier_task_runner(
            repository=repository,
            runtime=failed_replay_runtime,
        ).run(
            TaskRunCommand(
                task_id=failed_created.state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                request_id="failed-replay",
                lease_owner="failed-replay-worker",
            )
        )
        if (
            failed_replay.status != "failed"
            or failed_replay_runtime.execution_count != 0
        ):
            raise AssertionError("ordinary TaskRunCommand retried failed task")

        bounded_created = await _create_task(
            repository=repository,
            user_id=user_id,
            thread_id=thread_id,
            draft=TaskPlanDraft(
                goal="分批执行",
                steps=[
                    TaskPlanStepDraft(
                        step_key="first",
                        title="第一步",
                        capability="conversation_read",
                        arguments={
                            "target": "exchange",
                            "selection": "latest",
                            "count": 1,
                        },
                    ),
                    TaskPlanStepDraft(
                        step_key="second",
                        title="第二步",
                        capability="conversation_read",
                        arguments={
                            "target": "exchange",
                            "selection": "last_n",
                            "count": 2,
                        },
                        depends_on=["first"],
                    ),
                ],
            ),
        )
        first_runtime = _CountingRuntime()
        yielded = await build_verifier_task_runner(
            repository=repository,
            runtime=first_runtime,
        ).run(
            TaskRunCommand(
                task_id=bounded_created.state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                request_id="bounded-first",
                lease_owner="bounded-worker-1",
                max_batches=1,
            )
        )
        if yielded.status != "yielded":
            raise AssertionError("max_batches did not yield the running task")
        if yielded.task_state.lease_owner is not None:
            raise AssertionError("yielded task retained its lease")
        if yielded.task_state.recovery_cursor != 1:
            raise AssertionError("first bounded batch was not projected")

        second_runtime = _CountingRuntime()
        completed = await build_verifier_task_runner(
            repository=repository,
            runtime=second_runtime,
        ).run(
            TaskRunCommand(
                task_id=bounded_created.state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                request_id="bounded-second",
                lease_owner="bounded-worker-2",
                max_batches=1,
            )
        )
        if completed.status != "completed":
            raise AssertionError("yielded task did not resume to completion")
        if first_runtime.execution_count != 1:
            raise AssertionError("first bounded runner count is wrong")
        if second_runtime.execution_count != 1:
            raise AssertionError("second bounded runner repeated prior work")
        if completed.task_state.recovery_cursor != 2:
            raise AssertionError("bounded resume cursor is not exact")

        print("task runner verification passed")
        print("waiting_action_executions=1")
        print("waiting_completed_refs=0")
        print("waiting_projected_refs=1")
        print("waiting_implicit_resumes=0")
        print("failed_action_executions=1")
        print("failed_implicit_retries=0")
        print("bounded_first_executions=1")
        print("bounded_second_executions=1")
        print("bounded_final_cursor=2")
        print("yielded_lease_owner=none")
        print(f"fixture_registry={FIXTURE_REGISTRY_NAME}")
    finally:
        async with database.session() as session:
            await session.execute(
                text("DELETE FROM public.users WHERE id = :user_id"),
                {"user_id": user_id},
            )
        await dispose_database()


if __name__ == "__main__":
    asyncio.run(_run())
