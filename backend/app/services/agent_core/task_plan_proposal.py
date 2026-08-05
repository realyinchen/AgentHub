from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.tasks.contracts import TaskPlanDraft, TaskPlanStepDraft


CONTROLLER_TASK_PLAN_PROPOSAL_VERSION = "controller-task-plan-proposal-v1"


class ControllerTaskPlanProposal(BaseModel):
    """Model-visible proposal for work that is inherently multi-step."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[
        "controller-task-plan-proposal-v1"
    ] = CONTROLLER_TASK_PLAN_PROPOSAL_VERSION
    goal: str = Field(min_length=1, max_length=4_000)
    steps: list[TaskPlanStepDraft] = Field(min_length=2, max_length=64)
    success_criteria: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_durable_plan(self) -> "ControllerTaskPlanProposal":
        self.to_task_plan_draft()
        return self

    def to_task_plan_draft(self) -> TaskPlanDraft:
        """Convert a validated model proposal into the durable plan contract."""

        return TaskPlanDraft(
            goal=self.goal,
            steps=self.steps,
            success_criteria=self.success_criteria,
        )


__all__ = [
    "CONTROLLER_TASK_PLAN_PROPOSAL_VERSION",
    "ControllerTaskPlanProposal",
]
