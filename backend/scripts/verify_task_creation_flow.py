"""Verify task creation is typed, runtime-owned, shadow-safe, and idempotent."""

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
from app.services.agent_core.contracts import ControllerOutput
from app.services.agent_runtime import ExecutionContext
from app.services.tasks.contracts import (
    TaskPlanDraft,
    TaskPlanMutationReceipt,
    TaskPlanStepDraft,
)
from scripts.agent_core_verifier_fixtures import (
    FIXTURE_REGISTRY_NAME,
    build_verifier_harness,
)
from scripts.init_database import _init_postgres


def _draft(*, count: int = 1) -> TaskPlanDraft:
    return TaskPlanDraft(
        goal="读取最近的完整对话",
        steps=[
            TaskPlanStepDraft(
                step_key="read_history",
                title="读取对话",
                capability="conversation_read",
                arguments={
                    "target": "exchange",
                    "selection": "last_n",
                    "count": count,
                },
                completion_criteria="返回完整的用户与助手配对",
            )
        ],
        success_criteria=["读取结果保持角色配对"],
    )


def _output(*, count: int = 1) -> ControllerOutput:
    return ControllerOutput(
        mode="task_plan_proposal",
        task_plan_proposal=_draft(count=count),
    )


async def _counts(thread_id: uuid.UUID) -> tuple[int, int]:
    database = get_database()
    async with database.session() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT ts.task_id) AS task_count,
                    COUNT(tpv.id) AS version_count
                FROM public.task_states AS ts
                LEFT JOIN public.task_plan_versions AS tpv
                  ON tpv.task_id = ts.task_id
                WHERE ts.thread_id = :thread_id
                """
            ),
            {"thread_id": thread_id},
        )
        row = result.one()
    return int(row.task_count), int(row.version_count)


def _creation_receipt(result) -> TaskPlanMutationReceipt:
    if result.receipt is None or not result.receipt.actions:
        raise AssertionError("task creation produced no action receipt")
    action = result.receipt.actions[0]
    if action.operation != "plan_task_v1":
        raise AssertionError("task creation bypassed plan_task_v1")
    if action.metadata.get("runtime_dispatch") != "system_runtime":
        raise AssertionError("task creation bypassed SystemRuntime")
    return TaskPlanMutationReceipt.model_validate(action.output)


async def _run() -> None:
    _init_postgres()
    await init_database_connection()
    database = get_database()
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    request_id = f"task-create-{uuid.uuid4()}"
    try:
        async with database.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.users (id, display_name, is_mock_user)
                    VALUES
                      (:user_id, 'Task Creation Verify', true),
                      (:other_user_id, 'Task Creation Other User', true)
                    """
                ),
                {
                    "user_id": user_id,
                    "other_user_id": other_user_id,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO public.conversations (thread_id, user_id, title)
                    VALUES (:thread_id, :user_id, 'Task Creation Verify')
                    """
                ),
                {"thread_id": thread_id, "user_id": user_id},
            )

        context = ExecutionContext(
            user_id=user_id,
            thread_id=thread_id,
            request_id=request_id,
        )
        harness = build_verifier_harness()

        before = await _counts(thread_id)
        shadow = await harness.run(
            _output(),
            goal="请创建一个读取最近对话的任务",
            context=context,
            execution_mode="shadow",
        )
        after_shadow = await _counts(thread_id)
        if before != (0, 0) or after_shadow != before:
            raise AssertionError("shadow task creation changed business tables")
        if shadow.shadow is None or not shadow.shadow.valid:
            raise AssertionError("shadow task creation did not fully validate")

        first, replay = await asyncio.gather(
            harness.run(
                _output(),
                goal="请创建一个读取最近对话的任务",
                context=context,
            ),
            harness.run(
                _output(),
                goal="请创建一个读取最近对话的任务",
                context=context,
            ),
        )
        receipts = [_creation_receipt(first), _creation_receipt(replay)]
        if sum(item.mutation == "created" for item in receipts) != 1:
            raise AssertionError("concurrent replay did not create exactly once")
        if len({item.task_id for item in receipts}) != 1:
            raise AssertionError("concurrent replay returned different tasks")
        if len({item.plan_version_id for item in receipts}) != 1:
            raise AssertionError("concurrent replay returned different plan v1")
        if not first.answer.receipt_backed or not replay.answer.receipt_backed:
            raise AssertionError("task publication was not receipt-backed")

        task_count, version_count = await _counts(thread_id)
        if (task_count, version_count) != (1, 1):
            raise AssertionError("idempotent replay persisted duplicate rows")

        conflict = await harness.run(
            _output(count=2),
            goal="请创建一个不同的任务",
            context=context,
        )
        if conflict.receipt.status != "blocked":
            raise AssertionError("different draft reused one origin request")
        conflict_mutation = _creation_receipt(conflict)
        if conflict_mutation.reason != "origin_request_conflict":
            raise AssertionError("task conflict was not safely published")
        if await _counts(thread_id) != (1, 1):
            raise AssertionError("conflicting replay changed task tables")

        cross_user = await harness.run(
            _output(),
            goal="越权创建",
            context=ExecutionContext(
                user_id=other_user_id,
                thread_id=thread_id,
                request_id=f"cross-user-{uuid.uuid4()}",
            ),
        )
        if cross_user.receipt.status != "blocked":
            raise AssertionError("cross-user task creation was admitted")
        if await _counts(thread_id) != (1, 1):
            raise AssertionError("cross-user attempt changed task tables")

        print("task creation verification passed")
        print("task_rows=1")
        print("plan_v1_rows=1")
        print("concurrent_created_receipts=1")
        print("concurrent_reused_receipts=1")
        print("conflicting_replay=blocked")
        print("cross_user_creation=blocked")
        print("shadow_business_writes=0")
        print(f"fixture_registry={FIXTURE_REGISTRY_NAME}")
        print("publication=receipt_backed")
    finally:
        async with database.session() as session:
            await session.execute(
                text(
                    "DELETE FROM public.users "
                    "WHERE id IN (:user_id, :other_user_id)"
                ),
                {
                    "user_id": user_id,
                    "other_user_id": other_user_id,
                },
            )
        await dispose_database()


if __name__ == "__main__":
    asyncio.run(_run())
