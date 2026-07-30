from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.services.agent_core.contracts import (
    AgentCoreModel,
    ControllerMode,
)


ShadowControllerResultStatus = Literal[
    "denied",
    "shadow_valid",
    "shadow_invalid",
    "failed",
]
ShadowViolationCode = Literal[
    "system_owned_field",
    "unreceipted_success_claim",
    "memory_precommit_not_ready",
]


class ShadowObservationAppend(AgentCoreModel):
    observation_key: str = Field(pattern="^[0-9a-f]{64}$")
    user_id: UUID
    thread_id: UUID
    request_id: str = Field(min_length=1, max_length=128)
    journal_sequence_watermark: int = Field(ge=1)
    model_id: UUID | None = None
    certification_id: UUID | None = None
    configuration_fingerprint: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{64}$",
    )
    source_commit_sha: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{40}$",
    )
    controller_fingerprint: str = Field(
        pattern="^[0-9a-f]{64}$"
    )
    agent_core_contract_version: str = Field(
        min_length=1,
        max_length=64,
    )
    certification_contract_version: str = Field(
        min_length=1,
        max_length=64,
    )
    prompt_version: str = Field(min_length=1, max_length=64)
    context_snapshot_hash: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{64}$",
    )
    input_evidence_hash: str = Field(pattern="^[0-9a-f]{64}$")
    controller_status: ShadowControllerResultStatus
    output_mode: ControllerMode | None = None
    valid: bool | None = None
    would_execute: bool = False
    side_effect_count: int = Field(default=0, ge=0)
    latency_ms: int = Field(ge=0)
    proposal_summary: dict[str, Any] = Field(default_factory=dict)
    plan_summary: dict[str, Any] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    violation_codes: list[ShadowViolationCode] = Field(default_factory=list)
    error_hashes: list[str] = Field(default_factory=list)


class ShadowObservation(ShadowObservationAppend):
    id: UUID
    created_at: datetime


__all__ = [
    "ShadowControllerResultStatus",
    "ShadowObservation",
    "ShadowObservationAppend",
    "ShadowViolationCode",
]
