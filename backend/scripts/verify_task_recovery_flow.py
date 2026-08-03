"""Verify task recovery reconciles durable receipts without re-execution."""

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
from app.services.agent_runtime import (
    ActionReceipt,
    ExecutionContext,
    SystemRuntime,
)
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
    build_task_plan_compiler,
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
            output={"verified": action.metadata["task_step_key"]},
            admitted=True,
        )


async def _run() -> None:
    _init_postgres()
    await init_database_connection()
    database = get_database()
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    owner = "task-recovery-worker-1"
    repository = TaskRepository()
    try:
        async with database.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.users (id, display_name, is_mock_user)
                    VALUES (:user_id, 'Task Recovery Verify', true)
                    """
                ),
                {"user_id": user_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO public.conversations (thread_id, user_id, title)
                    VALUES (:thread_id, :user_id, 'Task Recovery Verify')
                    """
                ),
                {"thread_id": thread_id, "user_id": user_id},
            )

        draft = TaskPlanDraft(
            goal="先读取一轮，再读取一轮",
            steps=[
                TaskPlanStepDraft(
                    step_key="first_read",
                    title="读取最近一轮",
                    capability="conversation_read",
                    arguments={
                        "target": "exchange",
                        "selection": "latest",
                        "count": 1,
                    },
                ),
                TaskPlanStepDraft(
                    step_key="second_read",
                    title="再次读取",
                    capability="conversation_read",
                    arguments={
                        "target": "exchange",
                        "selection": "last_n",
                        "count": 2,
                    },
                    depends_on=["first_read"],
                ),
            ],
        )
        async with database.session() as session:
            created = await repository.create_v1(
                session,
                user_id=user_id,
                thread_id=thread_id,
                origin_request_id=f"task-recovery-{uuid.uuid4()}",
                validated=build_task_plan_validator().validate(draft),
            )
            state = created.state
            version = created.plan_version
        async with database.session() as session:
            state = await repository.claim_start_or_recover(
                session,
                state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                owner=owner,
                lease_seconds=60,
            )

        try:
            async with database.session() as session:
                await repository.claim_start_or_recover(
                    session,
                    state.task_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    owner="competing-worker",
                    lease_seconds=60,
                )
        except TaskLeaseError:
            pass
        else:
            raise AssertionError("competing worker acquired an active lease")

        compiler = build_task_plan_compiler()
        first = compiler.compile_next(version, completed_step_keys=set())
        if first.plan is None:
            raise AssertionError("first task batch was not compiled")
        first_runtime = _CountingRuntime()
        first_receipt = await first_runtime.execute(
            first.plan,
            context=ExecutionContext(
                user_id=user_id,
                thread_id=thread_id,
                request_id="task-recovery-original-request",
                task_id=state.task_id,
                plan_version_id=version.id,
                lease_owner=owner,
            ),
        )
        if first_runtime.execution_count != 1:
            raise AssertionError("first action did not execute exactly once")
        if first_receipt.status != "completed":
            raise AssertionError("first task batch did not complete")

        # Crash gap: Receipt is committed, TaskState remains unprojected.
        async with database.session() as session:
            gap_state = await repository.get(session, state.task_id)
        if gap_state.recovery_cursor != 0:
            raise AssertionError("ExecutionLedger wrote TaskState implicitly")

        recovered_runtime = _CountingRuntime()
        recovered = await build_verifier_task_runner(
            repository=repository,
            runtime=recovered_runtime,
        ).run(
            TaskRunCommand(
                task_id=state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                request_id="task-recovery-new-request",
                lease_owner=owner,
                lease_seconds=60,
                max_batches=16,
            )
        )
        if recovered.status != "completed":
            raise AssertionError("recovered task did not complete")
        if recovered_runtime.execution_count != 1:
            raise AssertionError(
                "recovery did not execute exactly the remaining action"
            )
        if recovered.task_state.recovery_cursor != 2:
            raise AssertionError("task receipt cursor did not reach two")
        if len(recovered.task_state.projected_receipt_refs) != 2:
            raise AssertionError("task receipt projection is incomplete")
        if len(recovered.task_state.completed_receipt_refs) != 2:
            raise AssertionError("completed task receipt refs are incomplete")

        repeated = await build_verifier_task_runner(
            repository=repository,
            runtime=_CountingRuntime(),
        ).run(
            TaskRunCommand(
                task_id=state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                request_id="task-recovery-terminal-replay",
                lease_owner="terminal-worker",
            )
        )
        if repeated.status != "completed":
            raise AssertionError("terminal replay changed task outcome")
        if repeated.task_state.recovery_cursor != 2:
            raise AssertionError("terminal replay increased receipt cursor")

        try:
            async with database.session() as session:
                await repository.claim_start_or_recover(
                    session,
                    state.task_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    owner="late-worker",
                )
        except TaskLeaseError:
            pass
        else:
            raise AssertionError("terminal task acquired a new lease")

        print("task recovery verification passed")
        print("action_1_executions=1")
        print("action_1_recovery_executions=0")
        print("remaining_action_executions=1")
        print("cross_request_receipt_reuse=passed")
        print("ledger_task_state_writes=0")
        print("receipt_cursor=2")
        print("duplicate_projection_growth=0")
        print("competing_lease_acquisitions=0")
        print("terminal_reacquire=blocked")
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
