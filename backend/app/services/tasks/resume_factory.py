from __future__ import annotations

from app.services.agent_runtime.contracts import ExecutionContext
from app.services.tasks.contracts import TaskPlanMutationReceipt
from app.services.tasks.runner_contracts import TaskResumeCommand


class TaskResumeCommandFactory:
    """Convert only a receipt-proven persisted revision into a trusted command."""

    def create(
        self,
        receipt: TaskPlanMutationReceipt,
        *,
        context: ExecutionContext,
        lease_owner: str,
        lease_seconds: int = 30,
        max_batches: int = 16,
    ) -> TaskResumeCommand:
        if (
            receipt.status != "completed"
            or receipt.mutation not in {"revised", "reused"}
            or not receipt.resume_required
        ):
            raise ValueError(
                "resume requires a successful persisted task revision"
            )
        if (
            receipt.task_id is None
            or receipt.plan_version_id is None
            or receipt.state_version is None
        ):
            raise ValueError(
                "revision receipt lacks trusted task identity"
            )
        if context.thread_id is None:
            raise ValueError("task resume requires a conversation thread")
        return TaskResumeCommand(
            task_id=receipt.task_id,
            plan_version_id=receipt.plan_version_id,
            expected_state_version=receipt.state_version,
            user_id=context.user_id,
            thread_id=context.thread_id,
            request_id=context.request_id,
            lease_owner=lease_owner,
            lease_seconds=lease_seconds,
            max_batches=max_batches,
        )


__all__ = ["TaskResumeCommandFactory"]
