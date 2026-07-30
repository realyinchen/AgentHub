from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from app.services.tasks.contracts import (
    TaskPlanDraft,
    ValidatedTaskPlanDraft,
)


class CapabilitySpecPort(Protocol):
    name: str
    input_model: type[BaseModel]
    side_effect: bool
    task_plan_allowed: bool


class CapabilityRegistryPort(Protocol):
    def require_enabled(self, name: str) -> CapabilitySpecPort: ...

    @property
    def task_planning_enabled(self) -> bool: ...


class TaskPlanDraftValidator:
    """Validate and normalize semantic task steps without persistence."""

    def __init__(
        self,
        registry: CapabilityRegistryPort | None = None,
    ) -> None:
        if registry is None:
            from app.services.agent_core.capabilities import (
                CapabilityRegistry,
            )

            registry = CapabilityRegistry()
        self._registry = registry

    def validate(self, draft: TaskPlanDraft) -> ValidatedTaskPlanDraft:
        if not self._registry.task_planning_enabled:
            raise ValueError("task planning capability is not enabled")
        normalized_steps = []
        side_effect_step_keys: list[str] = []
        for step in draft.steps:
            spec = self._registry.require_enabled(step.capability)
            if not getattr(spec, "task_plan_allowed", True):
                raise ValueError(
                    f"capability cannot be used as a durable task step: "
                    f"{spec.name}"
                )
            arguments = spec.input_model.model_validate(step.arguments)
            normalized_steps.append(
                step.model_copy(
                    update={
                        "capability": spec.name,
                        "arguments": arguments.model_dump(mode="json"),
                    }
                )
            )
            if spec.side_effect:
                side_effect_step_keys.append(step.step_key)
        return ValidatedTaskPlanDraft(
            draft=draft.model_copy(update={"steps": normalized_steps}),
            side_effect_step_keys=side_effect_step_keys,
        )


__all__ = [
    "CapabilityRegistryPort",
    "CapabilitySpecPort",
    "TaskPlanDraftValidator",
]
