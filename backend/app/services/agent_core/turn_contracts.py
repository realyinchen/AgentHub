from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.services.agent_core.contracts import (
    AgentCoreModel,
    ControllerOutput,
    PublishedAnswer,
)
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt


TurnStatus = Literal[
    "completed",
    "clarification_required",
    "failed",
    "limit_exceeded",
]


class ControllerRoundReceipt(AgentCoreModel):
    round_no: int = Field(ge=1, le=6)
    output: ControllerOutput
    plan: ActionPlan | None = None
    receipt: PlanReceipt | None = None
    answer: PublishedAnswer | None = None


class TurnReceipt(AgentCoreModel):
    result_mode: Literal["turn_receipt"] = "turn_receipt"
    status: TurnStatus
    request_id: str = Field(min_length=1, max_length=128)
    rounds: list[ControllerRoundReceipt] = Field(
        default_factory=list,
        max_length=6,
    )
    plan_receipts: list[PlanReceipt] = Field(default_factory=list, max_length=6)
    final_answer: PublishedAnswer

    @model_validator(mode="after")
    def validate_final_status(self) -> "TurnReceipt":
        expected = {
            "completed": "completed",
            "clarification_required": "clarification_required",
            "failed": "failed",
            "limit_exceeded": "failed",
        }[self.status]
        if self.final_answer.status != expected:
            raise ValueError(
                "turn status does not match the published answer status"
            )
        return self


__all__ = [
    "ControllerRoundReceipt",
    "TurnReceipt",
    "TurnStatus",
]
