from __future__ import annotations

from app.services.agent_runtime.contracts import (
    ActionPlan,
    PlannedAction,
    PlanSource,
)
from app.services.tasks.contracts import ValidatedTaskPlanDraft


class TaskCreationCompiler:
    """Purely compile one validated draft into a task-creation action."""

    def compile(
        self,
        validated: ValidatedTaskPlanDraft,
        *,
        goal: str,
        source: PlanSource = "controller_proposal",
    ) -> ActionPlan:
        draft = validated.draft
        return ActionPlan(
            source=source,
            route_type="slow_path",
            intent="create_task",
            goal=goal,
            confidence=1.0,
            complexity="high",
            planner_used=True,
            response_mode="receipt",
            actions=[
                PlannedAction(
                    action_id="create-task-v1",
                    capability="task",
                    operation="create_task_v1",
                    arguments={
                        "draft": draft.model_dump(mode="json"),
                    },
                    reason=(
                        "Persist one immutable task plan version through "
                        "SystemRuntime."
                    ),
                )
            ],
            metadata={
                "task_plan_contract": draft.contract_version,
                "compiled_from": "controller_task_plan",
            },
        )


__all__ = ["TaskCreationCompiler"]
