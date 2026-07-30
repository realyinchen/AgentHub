from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from app.services.agent_core.contracts import AgentCoreModel


class R4CapabilityCanaryEvidence(AgentCoreModel):
    """De-identified evidence for one explicit, non-release R4 canary."""

    evidence_version: Literal[
        "r4-capability-canary-v2"
    ] = "r4-capability-canary-v2"
    capability: Literal[
        "weather_get",
        "web_search",
        "book_search",
        "research_start",
    ]
    status: Literal["passed", "failed"]
    source_commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    model_id: str
    provider_model_id: str
    controller_mode: str
    proposed_capabilities: list[str] = Field(default_factory=list)
    compiled_operations: list[str] = Field(default_factory=list)
    plan_status: str = ""
    source_count: int = Field(default=0, ge=0)
    model_phase_status: Literal["passed", "failed", "not_run"] = "not_run"
    runtime_phase_status: Literal["passed", "failed", "not_run"] = "not_run"
    runtime_input_source: Literal[
        "model_proposal",
        "registered_fixture",
        "not_run",
    ] = "not_run"
    model_failure_code: str = Field(default="", max_length=128)
    runtime_failure_code: str = Field(default="", max_length=128)
    provider_identity_exposed: bool = False
    raw_provider_dump_exposed: bool = False
    system_owned_fields_exposed: bool = False
    release_gate_credit: Literal[False] = False
    failure_code: str = Field(default="", max_length=128)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


__all__ = ["R4CapabilityCanaryEvidence"]
