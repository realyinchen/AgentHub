from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.evidence_source import GitSourceState


DEVELOPER_SHADOW_PREVIEW_VERSION = "developer-shadow-preview-v2"


class DeveloperShadowPreviewCommand(AgentCoreModel):
    base_url: str = Field(min_length=1, max_length=512)
    commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    remote_ref: str = Field(pattern="^[A-Za-z0-9._/-]{1,256}$")
    model_id: UUID
    golden_artifact: str = Field(min_length=1, max_length=1_024)
    turn_count: int = Field(default=20, ge=20, le=50)
    http_timeout_seconds: float = Field(default=120, gt=0, le=600)
    observation_timeout_seconds: float = Field(default=300, gt=0, le=1_800)


class DeveloperShadowCoverage(AgentCoreModel):
    requested: int = Field(ge=20, le=50)
    accepted: int = Field(ge=0, le=50)
    enrolled: int = Field(ge=0, le=50)
    observed: int = Field(ge=0, le=50)
    shadow_valid: int = Field(ge=0, le=50)
    terminal: int = Field(ge=0, le=50)
    watermark_match: int = Field(ge=0, le=50)
    violation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_passed_coverage(self) -> "DeveloperShadowCoverage":
        expected = self.requested
        if any(
            value != expected
            for value in (
                self.accepted,
                self.enrolled,
                self.observed,
                self.shadow_valid,
                self.terminal,
                self.watermark_match,
            )
        ):
            raise ValueError("developer Shadow coverage is incomplete")
        if self.violation_count != 0:
            raise ValueError("developer Shadow coverage contains violations")
        return self


class DeveloperShadowBusinessWrites(AgentCoreModel):
    memory_events: int = Field(ge=0)
    task_states: int = Field(ge=0)
    task_plan_versions: int = Field(ge=0)
    research_runs: int = Field(ge=0)
    shadow_audit_receipts: int = Field(ge=0)
    legacy_request_receipts: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_isolation(self) -> "DeveloperShadowBusinessWrites":
        if any(
            value != 0
            for value in (
                self.memory_events,
                self.task_states,
                self.task_plan_versions,
                self.research_runs,
                self.shadow_audit_receipts,
            )
        ):
            raise ValueError("developer Shadow produced forbidden writes")
        return self


class DeveloperShadowCleanup(AgentCoreModel):
    users: int = Field(ge=0)
    conversations: int = Field(ge=0)
    conversation_events: int = Field(ge=0)
    shadow_observations: int = Field(ge=0)
    memory_events: int = Field(ge=0)
    task_states: int = Field(ge=0)
    task_plan_versions: int = Field(ge=0)
    research_runs: int = Field(ge=0)
    request_receipts: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_cleanup(self) -> "DeveloperShadowCleanup":
        if any(self.model_dump().values()):
            raise ValueError("developer Shadow mock identity cleanup is incomplete")
        return self


class DeveloperShadowPreviewArtifact(AgentCoreModel):
    artifact_version: Literal["developer-shadow-preview-v2"] = (
        DEVELOPER_SHADOW_PREVIEW_VERSION
    )
    status: Literal["passed"] = "passed"
    preview_state: Literal["developer_effect_preview"] = (
        "developer_effect_preview"
    )
    release_gate_credit: Literal[False] = False
    generated_at: datetime
    source_state: GitSourceState
    source_commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    remote_ref: str = Field(pattern="^[A-Za-z0-9._/-]{1,256}$")
    remote_commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    model_id: UUID
    admission_profile: Literal["developer_preview"] = "developer_preview"
    configured_thinking: bool
    certification_id: UUID
    configuration_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=64)
    golden_artifact_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    review_queue_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    base_url: str = Field(min_length=1, max_length=512)
    window_started_at: datetime
    window_ended_at: datetime
    coverage: DeveloperShadowCoverage
    business_writes: DeveloperShadowBusinessWrites
    response_modes: dict[str, int] = Field(default_factory=dict, max_length=16)
    difference_count: int = Field(ge=0, le=50)
    review_queue_candidate_count: int = Field(ge=0, le=50)
    raw_input_leakage_count: Literal[0] = 0
    cleanup: DeveloperShadowCleanup

    @model_validator(mode="after")
    def validate_preview(self) -> "DeveloperShadowPreviewArtifact":
        for value in (
            self.generated_at,
            self.window_started_at,
            self.window_ended_at,
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("developer Shadow timestamps must be timezone-aware")
        if self.window_ended_at <= self.window_started_at:
            raise ValueError("developer Shadow window is invalid")
        if self.generated_at < self.window_ended_at:
            raise ValueError("developer Shadow evidence predates its window")
        if self.source_state.dirty_worktree:
            raise ValueError("developer Shadow preview requires clean source")
        if (
            self.source_state.commit_sha != self.remote_commit_sha
            or self.source_state.commit_sha != self.source_commit_sha
        ):
            raise ValueError("developer Shadow source identity is inconsistent")
        if self.difference_count != self.review_queue_candidate_count:
            raise ValueError("developer Shadow differences are not fully queued")
        if sum(self.response_modes.values()) != self.coverage.accepted:
            raise ValueError("developer Shadow response modes are incomplete")
        if any(
            not key.strip() or value < 0
            for key, value in self.response_modes.items()
        ):
            raise ValueError("developer Shadow response modes are invalid")
        if self.response_modes.get("controller_v1", 0):
            raise ValueError("Shadow Controller handled a main response")
        return self


__all__ = [
    "DEVELOPER_SHADOW_PREVIEW_VERSION",
    "DeveloperShadowBusinessWrites",
    "DeveloperShadowCleanup",
    "DeveloperShadowCoverage",
    "DeveloperShadowPreviewArtifact",
    "DeveloperShadowPreviewCommand",
]
