from __future__ import annotations

from typing import Any

from app.infra.database import get_database
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.tasks.contracts import (
    CancellationReceipt,
    TaskCreationReceipt,
    TaskPlanDraft,
    TaskPlanMutationReceipt,
)
from app.services.tasks.coordinator import (
    TaskCancellationCoordinator,
    TaskPlanCoordinator,
)
from app.services.tasks.draft_validator import (
    CapabilityRegistryPort,
    TaskPlanDraftValidator,
)
from app.services.tasks.repository import (
    TaskConflictError,
    TaskNotFoundError,
    TaskRepository,
)


async def execute_create_task(
    arguments: dict[str, Any],
    *,
    context: ExecutionContext,
    capability_registry: CapabilityRegistryPort,
) -> dict[str, Any]:
    """Execute the one trusted task-creation operation."""

    if set(arguments) != {"draft"}:
        raise ValueError("task creation accepts only one typed draft")
    draft = TaskPlanDraft.model_validate(arguments["draft"])
    validated = TaskPlanDraftValidator(capability_registry).validate(draft)
    if context.thread_id is None:
        raise ValueError("task creation requires a conversation thread")

    database = get_database()
    try:
        async with database.session() as db:
            async with db.begin():
                result = await TaskRepository().create_v1(
                    db,
                    user_id=context.user_id,
                    thread_id=context.thread_id,
                    origin_request_id=context.request_id,
                    validated=validated,
                    source="controller",
                )
    except TaskConflictError:
        return TaskCreationReceipt(
            status="blocked",
            created=False,
            step_count=len(validated.draft.steps),
            reason="origin_request_conflict",
        ).model_dump(mode="json")
    except TaskNotFoundError:
        return TaskCreationReceipt(
            status="blocked",
            created=False,
            step_count=len(validated.draft.steps),
            reason="ownership_mismatch",
        ).model_dump(mode="json")

    return TaskCreationReceipt(
        task_id=result.state.task_id,
        plan_version_id=result.plan_version.id,
        version_no=result.plan_version.version_no,
        created=result.created,
        step_count=len(result.plan_version.draft.steps),
    ).model_dump(mode="json")


async def execute_plan_task(
    arguments: dict[str, Any],
    *,
    context: ExecutionContext,
    capability_registry: CapabilityRegistryPort,
) -> dict[str, Any]:
    """Execute one unified semantic task-plan proposal atomically."""

    if set(arguments) != {"draft"}:
        raise ValueError("task planning accepts only one typed draft")
    draft = TaskPlanDraft.model_validate(arguments["draft"])
    validated = TaskPlanDraftValidator(capability_registry).validate(draft)
    if context.thread_id is None:
        raise ValueError("task planning requires a conversation thread")

    database = get_database()
    async with database.session() as db:
        async with db.begin():
            receipt: TaskPlanMutationReceipt = (
                await TaskPlanCoordinator().coordinate(
                    db,
                    user_id=context.user_id,
                    thread_id=context.thread_id,
                    origin_request_id=context.request_id,
                    validated=validated,
                )
            )
    return receipt.model_dump(mode="json")


async def execute_cancel_active_task(
    arguments: dict[str, Any],
    *,
    context: ExecutionContext,
) -> dict[str, Any]:
    """Cancel the system-resolved active task for this conversation."""

    if set(arguments) - {"reason"}:
        raise ValueError("task cancellation accepts only an optional reason")
    reason = str(arguments.get("reason") or "")
    if len(reason) > 1_000:
        raise ValueError("task cancellation reason is too long")
    if context.thread_id is None:
        raise ValueError("task cancellation requires a conversation thread")

    database = get_database()
    async with database.session() as db:
        async with db.begin():
            receipt: CancellationReceipt = (
                await TaskCancellationCoordinator().cancel(
                    db,
                    user_id=context.user_id,
                    thread_id=context.thread_id,
                )
            )
    return receipt.model_dump(mode="json")


__all__ = [
    "execute_cancel_active_task",
    "execute_create_task",
    "execute_plan_task",
]
