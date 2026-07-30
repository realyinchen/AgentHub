from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.system_owned_fields import (
    ACTION_ARGUMENT_FORBIDDEN_FIELDS,
    find_forbidden_paths,
)

ACTION_PLAN_CONTRACT_VERSION = "action-plan-v1"
PLAN_RECEIPT_CONTRACT_VERSION = "plan-receipt-v1"

PlanSource = Literal[
    "routing_decision",
    "controller_proposal",
    "workflow_resume",
    "shadow_validation",
]
RouteType = Literal["fast_path", "slow_path"]
ResponseMode = Literal["deterministic", "receipt", "model"]
ReceiptStatus = Literal[
    "completed",
    "failed",
    "blocked",
    "skipped",
    "waiting",
]
PlanStatus = Literal[
    "completed",
    "partial",
    "failed",
    "blocked",
    "waiting",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PlannedAction(BaseModel):
    """One business action proposed by a rule or model planner.

    System-owned identity and request fields are intentionally forbidden from
    ``arguments``. They are injected from :class:`ExecutionContext` by the
    runtime after policy admission.
    """

    action_id: str = Field(default_factory=lambda: f"action-{uuid4()}")
    capability: str
    operation: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    required: bool = True
    depends_on: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("action_id", "capability", "operation", mode="before")
    @classmethod
    def clean_token(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("action token cannot be empty")
        return text

    @field_validator("arguments")
    @classmethod
    def reject_system_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        invalid = sorted(
            find_forbidden_paths(
                value,
                forbidden_fields=ACTION_ARGUMENT_FORBIDDEN_FIELDS,
            )
        )
        if invalid:
            raise ValueError(
                "system-owned fields are not valid action arguments: "
                + ", ".join(invalid)
            )
        return value


class ActionPlan(BaseModel):
    """The only contract that authorizes the system to perform actions."""

    result_mode: str = "action_plan"
    contract_version: str = ACTION_PLAN_CONTRACT_VERSION
    plan_id: str = Field(default_factory=lambda: f"plan-{uuid4()}")
    source: PlanSource
    route_type: RouteType
    intent: str
    goal: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    complexity: Literal["low", "medium", "high"] = "low"
    planner_used: bool = False
    response_mode: ResponseMode = "model"
    actions: list[PlannedAction] = Field(default_factory=list)
    forbidden_operations: list[str] = Field(default_factory=list)
    policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_unique_actions(self) -> "ActionPlan":
        ids = [action.action_id for action in self.actions]
        if len(ids) != len(set(ids)):
            raise ValueError("action_id values must be unique within one plan")
        known = set(ids)
        for action in self.actions:
            missing = [item for item in action.depends_on if item not in known]
            if missing:
                raise ValueError(
                    f"action {action.action_id} has unknown dependencies: {missing}"
                )
        return self


class ExecutionContext(BaseModel):
    """System-owned values unavailable to rule and LLM planners."""

    user_id: UUID
    thread_id: UUID | None = None
    request_id: str
    model_name: str = ""
    timezone: str = "Asia/Shanghai"
    permissions: list[str] = Field(default_factory=list)
    task_id: UUID | None = None
    plan_version_id: UUID | None = None
    lease_owner: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionReceipt(BaseModel):
    """Immutable-looking execution result consumed by finalizers and prompts."""

    action_id: str
    capability: str
    operation: str
    status: ReceiptStatus
    business_input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str = ""
    duration_ms: int = Field(default=0, ge=0)
    admitted: bool = False
    system_executed: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanReceipt(BaseModel):
    """System proof that an ActionPlan was admitted and executed."""

    result_mode: str = "plan_receipt"
    contract_version: str = PLAN_RECEIPT_CONTRACT_VERSION
    plan_id: str
    request_id: str
    route_type: RouteType
    intent: str
    planner_used: bool = False
    status: PlanStatus
    actions: list[ActionReceipt] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PreparedRuntimeTurn(BaseModel):
    """Plan and receipt prepared before answer generation."""

    plan: ActionPlan
    receipt: PlanReceipt

    @property
    def can_finalize_without_model(self) -> bool:
        return self.plan.response_mode in {"deterministic", "receipt"}
