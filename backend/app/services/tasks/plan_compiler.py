from __future__ import annotations

import hashlib
from uuid import UUID

from pydantic import Field

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.compiler import compile_capability
from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.plan_graph import PlanGraphNormalizer
from app.services.agent_runtime.contracts import (
    ActionPlan,
    PlannedAction,
)
from app.services.tasks.contracts import TaskPlanVersion


class TaskPlanCompilation(AgentCoreModel):
    status: str
    plan: ActionPlan | None = None
    ready_step_keys: list[str] = Field(default_factory=list)
    remaining_step_keys: list[str] = Field(default_factory=list)


class TaskPlanCompiler:
    """Compile only currently-ready task steps into one workflow_resume plan."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry | None = None,
        normalizer: PlanGraphNormalizer | None = None,
    ) -> None:
        self._registry = registry or CapabilityRegistry()
        self._normalizer = normalizer or PlanGraphNormalizer()

    def compile_next(
        self,
        version: TaskPlanVersion,
        *,
        completed_step_keys: set[str],
    ) -> TaskPlanCompilation:
        known = {step.step_key for step in version.draft.steps}
        invalid_completed = sorted(completed_step_keys - known)
        if invalid_completed:
            raise ValueError(
                f"completed task steps are unknown: {invalid_completed}"
            )
        remaining = [
            step
            for step in version.draft.steps
            if step.step_key not in completed_step_keys
        ]
        if not remaining:
            return TaskPlanCompilation(status="completed")
        ready = [
            step
            for step in remaining
            if set(step.depends_on).issubset(completed_step_keys)
        ]
        if not ready:
            return TaskPlanCompilation(
                status="blocked",
                remaining_step_keys=[step.step_key for step in remaining],
            )

        actions: list[PlannedAction] = []
        for step in ready:
            spec = self._registry.require_enabled(step.capability)
            payload = spec.input_model.model_validate(step.arguments)
            compiled = compile_capability(spec.name)
            actions.append(
                PlannedAction(
                    action_id=_action_id(
                        task_id=version.task_id,
                        plan_version_id=version.id,
                        step_key=step.step_key,
                    ),
                    capability=compiled.domain,
                    operation=compiled.operation,
                    arguments=payload.model_dump(mode="json"),
                    reason=step.title or compiled.reason,
                    metadata={
                        "task_step_key": step.step_key,
                        "task_plan_version": version.version_no,
                    },
                )
            )
        plan = self._normalizer.normalize(
            ActionPlan(
                plan_id=_plan_id(
                    task_id=version.task_id,
                    plan_version_id=version.id,
                    step_keys=[step.step_key for step in ready],
                ),
                source="workflow_resume",
                route_type="slow_path",
                intent="task_execution",
                goal=version.draft.goal,
                confidence=1,
                complexity="high",
                planner_used=True,
                response_mode="receipt",
                actions=actions,
                metadata={
                    "task_id": str(version.task_id),
                    "task_plan_version_id": str(version.id),
                    "task_plan_version": version.version_no,
                },
            )
        )
        return TaskPlanCompilation(
            status="ready",
            plan=plan,
            ready_step_keys=[step.step_key for step in ready],
            remaining_step_keys=[step.step_key for step in remaining],
        )

    @staticmethod
    def action_id(
        *,
        task_id: UUID,
        plan_version_id: UUID,
        step_key: str,
    ) -> str:
        return _action_id(
            task_id=task_id,
            plan_version_id=plan_version_id,
            step_key=step_key,
        )


def _action_id(
    *,
    task_id: UUID,
    plan_version_id: UUID,
    step_key: str,
) -> str:
    digest = hashlib.sha256(
        f"{task_id}:{plan_version_id}:{step_key}".encode("utf-8")
    ).hexdigest()[:32]
    return f"task-action-{digest}"


def _plan_id(
    *,
    task_id: UUID,
    plan_version_id: UUID,
    step_keys: list[str],
) -> str:
    material = ":".join(
        [str(task_id), str(plan_version_id), *sorted(step_keys)]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"task-plan-{digest}"


__all__ = ["TaskPlanCompilation", "TaskPlanCompiler"]
