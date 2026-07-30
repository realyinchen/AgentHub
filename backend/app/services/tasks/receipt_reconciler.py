from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import ActionExecutionReceiptRecord
from app.services.agent_core.compiler import compile_capability
from app.services.agent_runtime.contracts import ActionReceipt
from app.services.tasks.contracts import (
    TaskPlanVersion,
    TaskReceiptProjection,
    TaskReceiptProjectionResult,
)
from app.services.tasks.plan_compiler import TaskPlanCompiler
from app.services.tasks.repository import TaskRepository


class TaskReceiptReconciliationError(RuntimeError):
    pass


class TaskReceiptReconciler:
    """Project immutable task receipts into TaskState exactly once."""

    def __init__(self, *, repository: TaskRepository | None = None) -> None:
        self._repository = repository or TaskRepository()

    async def reconcile(
        self,
        db: AsyncSession,
        *,
        task_id: UUID,
        owner: str,
        version: TaskPlanVersion,
    ) -> TaskReceiptProjectionResult:
        if version.task_id != task_id:
            raise TaskReceiptReconciliationError(
                "task plan version does not belong to the task"
            )
        result = await db.execute(
            select(ActionExecutionReceiptRecord)
            .where(
                ActionExecutionReceiptRecord.task_id == task_id,
                ActionExecutionReceiptRecord.plan_version_id == version.id,
            )
            .order_by(
                ActionExecutionReceiptRecord.created_at.asc(),
                ActionExecutionReceiptRecord.id.asc(),
            )
        )
        records = list(result.scalars().all())
        expected = _expected_actions(version)
        seen_actions: set[str] = set()
        completed_step_keys: set[str] = set()
        receipt_refs_by_action: dict[str, str] = {}
        projections: list[TaskReceiptProjection] = []

        for record in records:
            expected_action = expected.get(record.action_id)
            if expected_action is None:
                raise TaskReceiptReconciliationError(
                    "task receipt references an unknown plan action"
                )
            if record.action_id in seen_actions:
                raise TaskReceiptReconciliationError(
                    "task plan action has multiple immutable receipts"
                )
            seen_actions.add(record.action_id)
            step_key, capability, operation, arguments = expected_action
            receipt = ActionReceipt.model_validate(record.receipt_json)
            if (
                record.status != receipt.status
                or record.capability != capability
                or record.operation != operation
                or receipt.action_id != record.action_id
                or receipt.capability != capability
                or receipt.operation != operation
                or receipt.business_input != arguments
            ):
                raise TaskReceiptReconciliationError(
                    "task receipt identity or payload does not match the plan"
                )
            receipt_ref = str(record.id)
            receipt_refs_by_action[record.action_id] = receipt_ref
            completed = receipt.status == "completed"
            projections.append(
                TaskReceiptProjection(
                    action_id=record.action_id,
                    receipt_ref=receipt_ref,
                    completed=completed,
                )
            )
            if completed:
                completed_step_keys.add(step_key)

        state = await self._repository.project_receipts(
            db,
            task_id,
            owner=owner,
            projections=projections,
        )
        ordered_completed = [
            step.step_key
            for step in version.draft.steps
            if step.step_key in completed_step_keys
        ]
        return TaskReceiptProjectionResult(
            state=state,
            completed_step_keys=ordered_completed,
            receipt_refs_by_action=receipt_refs_by_action,
        )


def _expected_actions(
    version: TaskPlanVersion,
) -> dict[str, tuple[str, str, str, dict]]:
    expected: dict[str, tuple[str, str, str, dict]] = {}
    for step in version.draft.steps:
        action_id = TaskPlanCompiler.action_id(
            task_id=version.task_id,
            plan_version_id=version.id,
            step_key=step.step_key,
        )
        compiled = compile_capability(step.capability)
        expected[action_id] = (
            step.step_key,
            compiled.domain,
            compiled.operation,
            dict(step.arguments),
        )
    return expected


__all__ = [
    "TaskReceiptReconciler",
    "TaskReceiptReconciliationError",
]
