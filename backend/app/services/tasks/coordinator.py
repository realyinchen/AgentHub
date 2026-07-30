from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tasks.contracts import (
    CancellationReceipt,
    TaskPlanMutationReceipt,
    ValidatedTaskPlanDraft,
)
from app.services.tasks.repository import (
    TaskConflictError,
    TaskNotFoundError,
    TaskRepository,
)
from app.services.tasks.revision_validator import TaskRevisionValidator


class TaskPlanCoordinator:
    """Atomically decide task create/revise inside one database transaction."""

    def __init__(
        self,
        *,
        repository: TaskRepository | None = None,
        revision_validator: TaskRevisionValidator | None = None,
    ) -> None:
        self._repository = repository or TaskRepository()
        self._revision_validator = (
            revision_validator or TaskRevisionValidator()
        )

    async def coordinate(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        origin_request_id: str,
        validated: ValidatedTaskPlanDraft,
    ) -> TaskPlanMutationReceipt:
        try:
            await self._repository.lock_conversation(
                db,
                user_id=user_id,
                thread_id=thread_id,
            )
        except TaskNotFoundError:
            return _blocked(
                validated,
                reason="ownership_mismatch",
            )

        try:
            existing = await self._repository.find_request_plan(
                db,
                user_id=user_id,
                thread_id=thread_id,
                origin_request_id=origin_request_id,
            )
        except TaskConflictError:
            return _blocked(
                validated,
                reason="origin_request_conflict",
            )
        if existing is not None:
            state, plan = existing
            if plan.draft.model_dump(mode="json") != (
                validated.draft.model_dump(mode="json")
            ):
                return _blocked(
                    validated,
                    reason="origin_request_conflict",
                )
            return _completed(
                mutation="reused",
                state=state,
                plan=plan,
                resume_required=(
                    plan.version_no > 1
                    and state.current_plan_version_id == plan.id
                    and state.status in {"waiting", "failed"}
                ),
            )

        active = await self._repository.active_for_thread(
            db,
            user_id=user_id,
            thread_id=thread_id,
        )
        if len(active) > 1:
            return _blocked(
                validated,
                reason="multiple_active_tasks",
            )
        if not active:
            created = await self._repository.create_v1(
                db,
                user_id=user_id,
                thread_id=thread_id,
                origin_request_id=origin_request_id,
                validated=validated,
                source="controller",
            )
            return _completed(
                mutation="created" if created.created else "reused",
                state=created.state,
                plan=created.plan_version,
                resume_required=False,
            )

        state = active[0]
        if state.status == "running":
            return _blocked(
                validated,
                reason="active_task_running",
            )
        if state.current_plan_version_id is None:
            return _blocked(
                validated,
                reason="revision_not_allowed",
            )
        current = await self._repository.get_plan_version(
            db,
            state.current_plan_version_id,
        )
        try:
            revision = self._revision_validator.validate(
                validated,
                state=state,
                current_plan=current,
            )
            record = await self._repository.append_validated_version(
                db,
                state.task_id,
                user_id=user_id,
                thread_id=thread_id,
                origin_request_id=origin_request_id,
                revision=revision,
                source="controller",
            )
        except (TaskConflictError, ValueError):
            return _blocked(
                validated,
                reason="revision_not_allowed",
            )
        return _completed(
            mutation="revised" if record.appended else "reused",
            state=record.state,
            plan=record.plan_version,
            resume_required=record.prior_status in {"waiting", "failed"},
        )


class TaskCancellationCoordinator:
    """Resolve and cancel the active task without model-visible identity."""

    def __init__(self, repository: TaskRepository | None = None) -> None:
        self._repository = repository or TaskRepository()

    async def cancel(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
    ) -> CancellationReceipt:
        try:
            state = await self._repository.cancel_active_for_thread(
                db,
                user_id=user_id,
                thread_id=thread_id,
            )
        except TaskNotFoundError:
            return CancellationReceipt(
                status="blocked",
                cancelled=False,
                reason="ownership_mismatch",
            )
        except TaskConflictError:
            return CancellationReceipt(
                status="blocked",
                cancelled=False,
                reason="multiple_active_tasks",
            )
        if state is None:
            return CancellationReceipt(
                status="blocked",
                cancelled=False,
                reason="no_active_task",
            )
        return CancellationReceipt(
            status="completed",
            cancelled=True,
        )


def _blocked(
    validated: ValidatedTaskPlanDraft,
    *,
    reason: str,
) -> TaskPlanMutationReceipt:
    return TaskPlanMutationReceipt(
        status="blocked",
        mutation="blocked",
        step_count=len(validated.draft.steps),
        reason=reason,
    )


def _completed(
    *,
    mutation: str,
    state,
    plan,
    resume_required: bool,
) -> TaskPlanMutationReceipt:
    return TaskPlanMutationReceipt(
        status="completed",
        mutation=mutation,
        task_id=state.task_id,
        plan_version_id=plan.id,
        version_no=plan.version_no,
        state_version=state.state_version,
        step_count=len(plan.draft.steps),
        resume_required=resume_required,
    )


__all__ = ["TaskCancellationCoordinator", "TaskPlanCoordinator"]
