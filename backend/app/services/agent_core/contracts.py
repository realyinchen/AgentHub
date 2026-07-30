from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt
from app.services.tasks.contracts import TaskPlanDraft


AGENT_CORE_CONTRACT_VERSION = "agent-core-v1"

ControllerMode = Literal[
    "direct_answer",
    "request_clarification",
    "task_plan_proposal",
    "capability_proposals",
]
ExecutionMode = Literal["live", "shadow"]


class AgentCoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ControllerToolCall(AgentCoreModel):
    call_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=32)


class ControllerOutput(AgentCoreModel):
    """Parsed model output. It is a proposal, never execution authority."""

    contract_version: Literal["agent-core-v1"] = AGENT_CORE_CONTRACT_VERSION
    mode: ControllerMode
    text: str = Field(default="", max_length=32_000)
    progress_text: str = Field(default="", max_length=4_000)
    tool_calls: list[ControllerToolCall] = Field(default_factory=list, max_length=16)
    task_plan_proposal: TaskPlanDraft | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> "ControllerOutput":
        if self.mode in {"direct_answer", "request_clarification"}:
            if not self.text.strip():
                raise ValueError(f"{self.mode} requires text")
            if self.tool_calls:
                raise ValueError(f"{self.mode} cannot contain tool calls")
            if self.task_plan_proposal is not None:
                raise ValueError(f"{self.mode} cannot contain a task plan")
        elif self.mode == "capability_proposals":
            if self.text.strip():
                raise ValueError(
                    "capability proposals cannot contain final answer text"
                )
            if not self.tool_calls:
                raise ValueError(
                    "capability_proposals requires at least one tool call"
                )
            if self.task_plan_proposal is not None:
                raise ValueError(
                    "capability proposals cannot contain a task plan"
                )
        elif self.mode == "task_plan_proposal":
            if self.text.strip():
                raise ValueError(
                    "task planning cannot contain final answer text"
                )
            if self.tool_calls:
                raise ValueError(
                    "task planning cannot contain capability tool calls"
                )
            if self.task_plan_proposal is None:
                raise ValueError(
                    "task_plan_proposal requires one typed task plan"
                )
        return self


class ValidatedCapabilityProposal(AgentCoreModel):
    call_id: str
    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    side_effect: bool = False


class CapabilityProposalBatch(AgentCoreModel):
    contract_version: Literal["agent-core-v1"] = AGENT_CORE_CONTRACT_VERSION
    proposals: list[ValidatedCapabilityProposal] = Field(
        default_factory=list,
        max_length=16,
    )


class PublishedAnswer(AgentCoreModel):
    result_mode: Literal["published_answer"] = "published_answer"
    contract_version: Literal["agent-core-v1"] = AGENT_CORE_CONTRACT_VERSION
    status: Literal[
        "completed",
        "clarification_required",
        "failed",
    ]
    content: str = Field(min_length=1, max_length=32_000)
    receipt_backed: bool = False
    receipt_refs: list[str] = Field(default_factory=list)


class ShadowEvaluationRecord(AgentCoreModel):
    result_mode: Literal["agent_core_shadow"] = "agent_core_shadow"
    contract_version: Literal["agent-core-v1"] = AGENT_CORE_CONTRACT_VERSION
    valid: bool
    would_execute: bool = False
    side_effect_count: int = Field(default=0, ge=0)
    plan: ActionPlan | None = None
    checks: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ShadowRunEvidence(AgentCoreModel):
    """De-identified evidence produced by one model-side Shadow decision."""

    context_snapshot_hash: str = Field(pattern="^[0-9a-f]{64}$")
    input_evidence_hash: str = Field(pattern="^[0-9a-f]{64}$")
    output_mode: ControllerMode
    proposal_summary: dict[str, Any] = Field(default_factory=dict)


class AgentCoreTurnResult(AgentCoreModel):
    result_mode: Literal["agent_core_turn"] = "agent_core_turn"
    contract_version: Literal["agent-core-v1"] = AGENT_CORE_CONTRACT_VERSION
    execution_mode: ExecutionMode
    output: ControllerOutput
    plan: ActionPlan | None = None
    receipt: PlanReceipt | None = None
    answer: PublishedAnswer | None = None
    shadow: ShadowEvaluationRecord | None = None
