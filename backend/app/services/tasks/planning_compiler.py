from __future__ import annotations

from app.services.agent_runtime.contracts import (
    ActionPlan,
    PlannedAction,
    PlanSource,
)
from app.services.tasks.contracts import ValidatedTaskPlanDraft


class TaskPlanningCompiler:
    """Compile one semantic plan proposal without choosing create or revise."""

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
            intent="plan_task",
            goal=goal,
            confidence=1.0,
            complexity="high",
            planner_used=True,
            response_mode="receipt",
            actions=[
                PlannedAction(
                    action_id="plan-task-v1",
                    capability="task",
                    operation="plan_task_v1",
                    arguments={
                        "draft": draft.model_dump(mode="json"),
                    },
                    reason=(
                        "Let the trusted task coordinator atomically create "
                        "or revise the active durable task."
                    ),
                )
            ],
            metadata={
                "task_plan_contract": draft.contract_version,
                "compiled_from": "controller_task_plan_proposal",
            },
        )


__all__ = ["TaskPlanningCompiler"]
