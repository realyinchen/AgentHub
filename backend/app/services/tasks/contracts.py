from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.system_owned_fields import (
    MODEL_PROPOSAL_FORBIDDEN_FIELDS,
    find_forbidden_paths,
)

TASK_PLAN_CONTRACT_VERSION = "task-plan-v1"
VALIDATED_TASK_PLAN_CONTRACT_VERSION = "validated-task-plan-v1"
TaskStatus = Literal[
    "pending",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
]

class TaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskPlanStepDraft(TaskModel):
    """Model-visible semantic step. step_key is local, not storage identity."""

    step_key: str = Field(pattern="^[a-z][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=500)
    capability: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=32)
    completion_criteria: str = Field(default="", max_length=1_000)

    @field_validator("arguments")
    @classmethod
    def reject_system_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        invalid = sorted(
            find_forbidden_paths(
                value,
                forbidden_fields=MODEL_PROPOSAL_FORBIDDEN_FIELDS,
            )
        )
        if invalid:
            raise ValueError(
                "task step contains system-owned fields: "
                + ", ".join(invalid)
            )
        return value


class TaskPlanDraft(TaskModel):
    contract_version: Literal["task-plan-v1"] = TASK_PLAN_CONTRACT_VERSION
    goal: str = Field(min_length=1, max_length=4_000)
    steps: list[TaskPlanStepDraft] = Field(min_length=1, max_length=64)
    success_criteria: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_graph(self) -> "TaskPlanDraft":
        keys = [step.step_key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("task step_key values must be unique")
        known = set(keys)
        graph = {step.step_key: list(step.depends_on) for step in self.steps}
        for step in self.steps:
            missing = sorted(set(step.depends_on) - known)
            if missing:
                raise ValueError(
                    f"task step {step.step_key} has unknown dependencies: {missing}"
                )
            if step.step_key in step.depends_on:
                raise ValueError(
                    f"task step {step.step_key} depends on itself"
                )
        _reject_cycles(graph)
        return self


class TaskPlanVersion(TaskModel):
    id: UUID
    task_id: UUID
    version_no: int = Field(ge=1)
    previous_version_id: UUID | None = None
    draft: TaskPlanDraft
    source: Literal["controller", "recovery", "operator"]
    origin_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    created_at: datetime


class ValidatedTaskPlanDraft(TaskModel):
    contract_version: Literal[
        "validated-task-plan-v1"
    ] = VALIDATED_TASK_PLAN_CONTRACT_VERSION
    draft: TaskPlanDraft
    side_effect_step_keys: list[str] = Field(default_factory=list)


class TaskPendingClarification(TaskModel):
    question: str = Field(min_length=1, max_length=4_000)
    step_key: str | None = Field(
        default=None,
        pattern="^[a-z][a-z0-9_]{0,63}$",
    )
    blocked_plan_version_id: UUID | None = None
    blocked_action_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    receipt_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


class TaskFailureProjection(TaskModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2_000)
    failed_plan_version_id: UUID | None = None
    failed_action_ids: list[str] = Field(default_factory=list, max_length=64)
    receipt_refs: list[str] = Field(default_factory=list, max_length=64)
    retryable: bool = False


class TaskStateSnapshot(TaskModel):
    task_id: UUID
    user_id: UUID
    thread_id: UUID
    origin_request_id: str | None = None
    status: TaskStatus
    current_plan_version_id: UUID | None = None
    current_action_id: str | None = None
    completed_receipt_refs: list[str] = Field(default_factory=list)
    projected_receipt_refs: list[str] = Field(default_factory=list)
    waiting_reason: str | None = None
    pending_clarification: TaskPendingClarification | None = None
    recovery_cursor: int = Field(ge=0)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    terminal_error: TaskFailureProjection | None = None
    state_version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_receipt_cursor(self) -> "TaskStateSnapshot":
        if len(self.projected_receipt_refs) != len(
            set(self.projected_receipt_refs)
        ):
            raise ValueError("projected receipt refs must be unique")
        if len(self.completed_receipt_refs) != len(
            set(self.completed_receipt_refs)
        ):
            raise ValueError("completed receipt refs must be unique")
        if self.recovery_cursor != len(self.projected_receipt_refs):
            raise ValueError(
                "recovery_cursor must equal projected receipt count"
            )
        if not set(self.completed_receipt_refs).issubset(
            self.projected_receipt_refs
        ):
            raise ValueError(
                "completed receipt refs must already be projected"
            )
        return self


class TaskReceiptProjection(TaskModel):
    action_id: str = Field(min_length=1, max_length=128)
    receipt_ref: str = Field(min_length=1, max_length=128)
    completed: bool = False


class TaskReceiptProjectionResult(TaskModel):
    state: TaskStateSnapshot
    completed_step_keys: list[str] = Field(default_factory=list)
    receipt_refs_by_action: dict[str, str] = Field(default_factory=dict)


class TaskCreationRecord(TaskModel):
    created: bool
    state: TaskStateSnapshot
    plan_version: TaskPlanVersion


class TaskCreationReceipt(TaskModel):
    result_mode: Literal["task_creation_receipt"] = "task_creation_receipt"
    status: Literal["completed", "blocked"] = "completed"
    task_id: UUID | None = None
    plan_version_id: UUID | None = None
    version_no: int | None = Field(default=None, ge=1)
    created: bool
    step_count: int = Field(ge=1)
    reason: Literal[
        "origin_request_conflict",
        "ownership_mismatch",
    ] | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "TaskCreationReceipt":
        identities = (
            self.task_id,
            self.plan_version_id,
            self.version_no,
        )
        if self.status == "completed":
            if any(value is None for value in identities):
                raise ValueError(
                    "completed task creation requires task identities"
                )
            if self.reason is not None:
                raise ValueError(
                    "completed task creation cannot contain a rejection reason"
                )
        else:
            if any(value is not None for value in identities):
                raise ValueError(
                    "blocked task creation cannot expose task identities"
                )
            if self.created or self.reason is None:
                raise ValueError(
                    "blocked task creation requires a reason and created=false"
                )
        return self


class ValidatedTaskPlanRevision(TaskModel):
    validated: ValidatedTaskPlanDraft
    base_plan_version_id: UUID
    expected_state_version: int = Field(ge=0)
    prior_status: Literal["pending", "waiting", "failed"]


class TaskPlanRevisionRecord(TaskModel):
    appended: bool
    prior_status: TaskStatus
    state: TaskStateSnapshot
    plan_version: TaskPlanVersion


class TaskPlanMutationReceipt(TaskModel):
    result_mode: Literal[
        "task_plan_mutation_receipt"
    ] = "task_plan_mutation_receipt"
    status: Literal["completed", "blocked"]
    mutation: Literal["created", "revised", "reused", "blocked"]
    task_id: UUID | None = None
    plan_version_id: UUID | None = None
    version_no: int | None = Field(default=None, ge=1)
    state_version: int | None = Field(default=None, ge=0)
    step_count: int = Field(ge=1)
    resume_required: bool = False
    reason: Literal[
        "active_task_running",
        "multiple_active_tasks",
        "origin_request_conflict",
        "ownership_mismatch",
        "revision_not_allowed",
    ] | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "TaskPlanMutationReceipt":
        identities = (
            self.task_id,
            self.plan_version_id,
            self.version_no,
            self.state_version,
        )
        if self.status == "completed":
            if self.mutation == "blocked":
                raise ValueError(
                    "completed task mutation cannot be blocked"
                )
            if any(value is None for value in identities):
                raise ValueError(
                    "completed task mutation requires system identities"
                )
            if self.reason is not None:
                raise ValueError(
                    "completed task mutation cannot contain a reason"
                )
            if self.resume_required and self.mutation not in {
                "revised",
                "reused",
            }:
                raise ValueError(
                    "only a persisted revision can require resume"
                )
        else:
            if self.mutation != "blocked" or self.reason is None:
                raise ValueError(
                    "blocked task mutation requires mutation=blocked and reason"
                )
            if any(value is not None for value in identities):
                raise ValueError(
                    "blocked task mutation cannot expose system identities"
                )
            if self.resume_required:
                raise ValueError(
                    "blocked task mutation cannot authorize resume"
                )
        return self


class CancellationReceipt(TaskModel):
    result_mode: Literal[
        "task_cancellation_receipt"
    ] = "task_cancellation_receipt"
    status: Literal["completed", "blocked"]
    cancelled: bool
    reason: Literal[
        "no_active_task",
        "multiple_active_tasks",
        "ownership_mismatch",
    ] | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "CancellationReceipt":
        if self.status == "completed":
            if not self.cancelled or self.reason is not None:
                raise ValueError(
                    "completed cancellation must prove cancellation"
                )
        elif self.cancelled or self.reason is None:
            raise ValueError(
                "blocked cancellation requires a reason and cancelled=false"
            )
        return self


def _reject_cycles(graph: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("task plan contains a dependency cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


__all__ = [
    "TASK_PLAN_CONTRACT_VERSION",
    "VALIDATED_TASK_PLAN_CONTRACT_VERSION",
    "CancellationReceipt",
    "TaskCreationReceipt",
    "TaskCreationRecord",
    "TaskFailureProjection",
    "TaskPendingClarification",
    "TaskPlanDraft",
    "TaskPlanMutationReceipt",
    "TaskPlanRevisionRecord",
    "TaskPlanStepDraft",
    "TaskPlanVersion",
    "TaskReceiptProjection",
    "TaskReceiptProjectionResult",
    "TaskStateSnapshot",
    "TaskStatus",
    "ValidatedTaskPlanDraft",
    "ValidatedTaskPlanRevision",
]
