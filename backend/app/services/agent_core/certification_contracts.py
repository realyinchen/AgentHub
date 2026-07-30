from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from app.services.agent_core.contracts import AgentCoreModel


AGENT_CERTIFICATION_CONTRACT_VERSION = "agent-capability-v4"

AgentProbeCaseName = Literal[
    "basic_chat",
    "strict_tool_schema",
    "streaming_tool_arguments",
    "multiple_tool_calls",
    "tool_message_roundtrip",
    "mixed_text_tool_call",
    "multilingual_context",
    "direct_answer_with_tools",
    "task_plan_schema",
    "tool_failure_termination",
]
AGENT_PROBE_CASE_NAMES: tuple[AgentProbeCaseName, ...] = (
    "basic_chat",
    "strict_tool_schema",
    "streaming_tool_arguments",
    "multiple_tool_calls",
    "tool_message_roundtrip",
    "mixed_text_tool_call",
    "multilingual_context",
    "direct_answer_with_tools",
    "task_plan_schema",
    "tool_failure_termination",
)
AGENT_PROBE_REQUIRED_CASE_NAMES: frozenset[AgentProbeCaseName] = frozenset(
    {
        "basic_chat",
        "strict_tool_schema",
        "tool_message_roundtrip",
        "multilingual_context",
        "direct_answer_with_tools",
        "task_plan_schema",
        "tool_failure_termination",
    }
)
AgentModeDenialReason = Literal[
    "certification_missing",
    "configuration_changed",
    "contract_changed",
    "controller_changed",
    "release_changed",
    "certification_failed",
]


class AgentProbeCaseResult(AgentCoreModel):
    name: AgentProbeCaseName
    required: bool = True
    passed: bool
    latency_ms: int = Field(ge=0)
    error_type: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1_000)
    observations: dict[str, Any] = Field(default_factory=dict)


class AgentCapabilityCertificationOutcome(AgentCoreModel):
    contract_version: Literal[
        "agent-capability-v4"
    ] = AGENT_CERTIFICATION_CONTRACT_VERSION
    certified: bool
    latency_ms: int = Field(ge=0)
    cases: list[AgentProbeCaseResult]
    failure_cases: list[AgentProbeCaseName] = Field(default_factory=list)


class AgentModeAdmission(AgentCoreModel):
    admitted: bool
    certification_id: str | None = None
    reason: AgentModeDenialReason | None = None
    configuration_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    contract_version: Literal[
        "agent-capability-v4"
    ] = AGENT_CERTIFICATION_CONTRACT_VERSION

    @model_validator(mode="after")
    def validate_admission(self) -> "AgentModeAdmission":
        if self.admitted:
            if not self.certification_id:
                raise ValueError("admitted Agent mode requires certification_id")
            if self.reason is not None:
                raise ValueError("admitted Agent mode cannot contain denial reason")
        else:
            if self.reason is None:
                raise ValueError("denied Agent mode requires a reason")
        return self


__all__ = [
    "AGENT_CERTIFICATION_CONTRACT_VERSION",
    "AGENT_PROBE_CASE_NAMES",
    "AGENT_PROBE_REQUIRED_CASE_NAMES",
    "AgentCapabilityCertificationOutcome",
    "AgentModeAdmission",
    "AgentModeDenialReason",
    "AgentProbeCaseName",
    "AgentProbeCaseResult",
]
