from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.services.agent_runtime.contracts import PlanReceipt
from app.services.tasks.contracts import TaskModel, TaskStateSnapshot


TaskRunStatus = Literal[
    "progressed",
    "waiting",
    "completed",
    "failed",
    "yielded",
]


class TaskRunCommand(TaskModel):
    """Trusted internal command for pending/running task execution only."""

    task_id: UUID
    user_id: UUID
    thread_id: UUID
    request_id: str = Field(min_length=1, max_length=128)
    lease_owner: str = Field(min_length=1, max_length=128)
    lease_seconds: int = Field(default=30, ge=5, le=300)
    max_batches: int = Field(default=16, ge=1, le=16)

    @field_validator("request_id", "lease_owner", mode="before")
    @classmethod
    def normalize_token(cls, value: object) -> str:
        return str(value or "").strip()


class TaskResumeCommand(TaskModel):
    """Trusted command proving a new version exists after waiting/failed."""

    task_id: UUID
    plan_version_id: UUID
    expected_state_version: int = Field(ge=0)
    user_id: UUID
    thread_id: UUID
    request_id: str = Field(min_length=1, max_length=128)
    lease_owner: str = Field(min_length=1, max_length=128)
    lease_seconds: int = Field(default=30, ge=5, le=300)
    max_batches: int = Field(default=16, ge=1, le=16)

    @field_validator("request_id", "lease_owner", mode="before")
    @classmethod
    def normalize_token(cls, value: object) -> str:
        return str(value or "").strip()

    def as_run_command(self) -> TaskRunCommand:
        return TaskRunCommand(
            task_id=self.task_id,
            user_id=self.user_id,
            thread_id=self.thread_id,
            request_id=self.request_id,
            lease_owner=self.lease_owner,
            lease_seconds=self.lease_seconds,
            max_batches=self.max_batches,
        )


class TaskRunReceipt(TaskModel):
    result_mode: Literal["task_run_receipt"] = "task_run_receipt"
    task_id: UUID
    status: TaskRunStatus
    task_state: TaskStateSnapshot
    plan_receipts: list[PlanReceipt] = Field(default_factory=list)
    completed_step_keys: list[str] = Field(default_factory=list)
    waiting_question: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def validate_status_projection(self) -> "TaskRunReceipt":
        expected = {
            "waiting": {"waiting"},
            "completed": {"completed"},
            "failed": {"failed", "cancelled"},
            "yielded": {"running"},
            "progressed": {"running"},
        }[self.status]
        if self.task_state.status not in expected:
            raise ValueError(
                "task run status does not match the persisted task state"
            )
        return self


__all__ = [
    "TaskResumeCommand",
    "TaskRunCommand",
    "TaskRunReceipt",
    "TaskRunStatus",
]
