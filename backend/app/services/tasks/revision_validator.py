from __future__ import annotations

from app.services.tasks.contracts import (
    TaskPlanVersion,
    TaskStateSnapshot,
    ValidatedTaskPlanDraft,
    ValidatedTaskPlanRevision,
)


class TaskRevisionValidator:
    """Validate only the trusted relationship between state and a new draft."""

    def validate(
        self,
        validated: ValidatedTaskPlanDraft,
        *,
        state: TaskStateSnapshot,
        current_plan: TaskPlanVersion,
    ) -> ValidatedTaskPlanRevision:
        if state.status not in {"pending", "waiting", "failed"}:
            raise ValueError(
                f"task status cannot be revised: {state.status}"
            )
        if state.current_plan_version_id != current_plan.id:
            raise ValueError("task current plan changed before revision")
        if current_plan.task_id != state.task_id:
            raise ValueError("task plan does not belong to task state")
        if state.status == "waiting":
            pending = state.pending_clarification
            if (
                pending is None
                or pending.blocked_plan_version_id != current_plan.id
            ):
                raise ValueError(
                    "waiting revision lacks blocked plan proof"
                )
        if state.status == "failed":
            failure = state.terminal_error
            if (
                failure is None
                or failure.failed_plan_version_id != current_plan.id
            ):
                raise ValueError(
                    "failed revision lacks failed plan proof"
                )
        return ValidatedTaskPlanRevision(
            validated=validated,
            base_plan_version_id=current_plan.id,
            expected_state_version=state.state_version,
            prior_status=state.status,
        )


__all__ = ["TaskRevisionValidator"]
