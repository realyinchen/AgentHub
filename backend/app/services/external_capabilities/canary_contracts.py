from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from app.services.agent_core.contracts import AgentCoreModel


class R4CapabilityCanaryEvidence(AgentCoreModel):
    """De-identified evidence for one explicit, non-release R4 canary."""

    evidence_version: Literal[
        "r4-capability-canary-v1"
    ] = "r4-capability-canary-v1"
    capability: Literal["weather_get"]
    status: Literal["passed", "failed"]
    source_commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    model_id: str
    provider_model_id: str
    controller_mode: str
    proposed_capabilities: list[str] = Field(default_factory=list)
    compiled_operations: list[str] = Field(default_factory=list)
    plan_status: str = ""
    source_count: int = Field(default=0, ge=0)
    provider_identity_exposed: bool = False
    raw_provider_dump_exposed: bool = False
    system_owned_fields_exposed: bool = False
    release_gate_credit: Literal[False] = False
    failure_code: str = Field(default="", max_length=128)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


__all__ = ["R4CapabilityCanaryEvidence"]

