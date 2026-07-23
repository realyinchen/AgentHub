from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TASK_PLAN_CONTRACT_VERSION = "task-plan-v1"


class ComplexityAssessment(BaseModel):
    level: Literal["low", "medium", "high"] = "low"
    planner_required: bool = False
    reasons: list[str] = Field(default_factory=list)
    constraint_count: int = Field(default=0, ge=0)
    required_action_count: int = Field(default=0, ge=0)


class TaskStep(BaseModel):
    step_id: str
    capability: str
    action: str
    input: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    required: bool = True


class TaskPlan(BaseModel):
    result_mode: str = "task_plan"
    contract_version: str = TASK_PLAN_CONTRACT_VERSION
    goal: str
    task_type: str
    complexity: ComplexityAssessment
    planner_type: str = "deterministic_template"
    steps: list[TaskStep] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
