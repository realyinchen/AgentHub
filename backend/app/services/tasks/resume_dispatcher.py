from __future__ import annotations

from app.infra.config import get_settings
from app.services.agent_runtime.contracts import ExecutionContext, PlanReceipt
from app.services.tasks.contracts import TaskPlanMutationReceipt
from app.services.tasks.resume_factory import TaskResumeCommandFactory
from app.services.tasks.runner import TaskRunner
from app.services.tasks.runner_contracts import TaskRunReceipt


class TaskResumeDispatcher:
    """Dispatch receipt-authorized task resume behind one system feature gate."""

    def __init__(
        self,
        *,
        factory: TaskResumeCommandFactory | None = None,
        runner: TaskRunner | None = None,
    ) -> None:
        self._factory = factory or TaskResumeCommandFactory()
        self._runner = runner or TaskRunner()

    async def dispatch(
        self,
        receipt: PlanReceipt,
        *,
        context: ExecutionContext,
        enabled: bool | None = None,
    ) -> TaskRunReceipt | None:
        active = (
            get_settings().AGENT_TASK_RESUME_V1
            if enabled is None
            else bool(enabled)
        )
        if not active:
            return None
        mutation = _revision_mutation(receipt)
        if mutation is None:
            return None
        command = self._factory.create(
            mutation,
            context=context,
            lease_owner=f"controller-resume:{context.request_id}"[:128],
        )
        return await self._runner.resume(command)


def _revision_mutation(
    receipt: PlanReceipt,
) -> TaskPlanMutationReceipt | None:
    for action in receipt.actions:
        if (
            action.operation != "plan_task_v1"
            or action.status != "completed"
            or not isinstance(action.output, dict)
        ):
            continue
        try:
            mutation = TaskPlanMutationReceipt.model_validate(
                action.output
            )
        except Exception:
            continue
        if (
            mutation.status == "completed"
            and mutation.mutation in {"revised", "reused"}
            and mutation.resume_required
        ):
            return mutation
    return None


__all__ = ["TaskResumeDispatcher"]
