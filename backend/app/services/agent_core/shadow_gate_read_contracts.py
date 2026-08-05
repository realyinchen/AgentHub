from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.shadow_observation_contracts import (
    ShadowObservation,
)


class ShadowGateReadRequest(AgentCoreModel):
    commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    configuration_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=64)
    window_started_at: datetime
    window_ended_at: datetime
    collected_at: datetime
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    grace_period_seconds: int = Field(default=300, ge=1, le=86_400)
    thread_id: UUID | None = None
    request_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_window(self) -> "ShadowGateReadRequest":
        for value in (
            self.window_started_at,
            self.window_ended_at,
            self.collected_at,
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    "Shadow window timestamps must be timezone-aware"
                )
        if self.window_ended_at <= self.window_started_at:
            raise ValueError("Shadow window end must follow its start")
        return self


class ShadowLegacyTerminal(AgentCoreModel):
    event_type: Literal[
        "assistant_published",
        "clarification_requested",
        "turn_failed",
    ]
    sequence_no: int = Field(ge=1)
    summary: dict[str, Any] = Field(default_factory=dict)


class ShadowGateRawTurn(AgentCoreModel):
    observation_key: str = Field(pattern="^[0-9a-f]{64}$")
    enrolled_at: datetime
    journal_sequence_watermark: int = Field(ge=1)
    terminal_events: list[ShadowLegacyTerminal] = Field(
        default_factory=list,
        max_length=2,
    )
    observation: ShadowObservation | None = None
    audit_receipt_count: int = Field(default=0, ge=0)


class ShadowGateRawWindow(AgentCoreModel):
    request: ShadowGateReadRequest
    turns: list[ShadowGateRawTurn] = Field(
        default_factory=list,
        max_length=100_000,
    )


__all__ = [
    "ShadowGateRawTurn",
    "ShadowGateRawWindow",
    "ShadowGateReadRequest",
    "ShadowLegacyTerminal",
]
