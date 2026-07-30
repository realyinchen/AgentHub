from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.shadow_gate_contracts import (
    ShadowCoverageSnapshot,
    ShadowGateDataset,
    ShadowGateReport,
)


SHADOW_GATE_EVIDENCE_VERSION = "shadow-gate-evidence-v1"


class ShadowGateDatasetSummary(AgentCoreModel):
    commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    configuration_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=64)
    timezone: Literal["Asia/Shanghai"]
    window_started_at: datetime
    window_ended_at: datetime
    collected_at: datetime
    grace_period_seconds: int = Field(ge=1, le=86_400)
    review_artifact_hash: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{64}$",
    )
    coverage: ShadowCoverageSnapshot

    @classmethod
    def from_dataset(
        cls,
        dataset: ShadowGateDataset,
    ) -> "ShadowGateDatasetSummary":
        return cls.model_validate(
            dataset.model_dump(exclude={"observations"})
        )


class ShadowGateEvidenceArtifact(AgentCoreModel):
    artifact_version: Literal["shadow-gate-evidence-v1"] = (
        SHADOW_GATE_EVIDENCE_VERSION
    )
    source_state: GitSourceState
    generated_at: datetime
    dataset: ShadowGateDatasetSummary
    report: ShadowGateReport

    @model_validator(mode="after")
    def validate_bindings(self) -> "ShadowGateEvidenceArtifact":
        if (
            self.generated_at.tzinfo is None
            or self.generated_at.utcoffset() is None
        ):
            raise ValueError(
                "Shadow Gate evidence generated_at must be timezone-aware"
            )
        if self.source_state.dirty_worktree:
            raise ValueError(
                "Shadow Gate evidence requires clean source"
            )
        if self.source_state.commit_sha != self.dataset.commit_sha:
            raise ValueError(
                "Shadow Gate evidence source commit mismatch"
            )
        if self.generated_at != self.dataset.collected_at:
            raise ValueError(
                "Shadow Gate evidence time does not match collection"
            )
        expected = (
            self.dataset.commit_sha,
            self.dataset.controller_fingerprint,
            self.dataset.configuration_fingerprint,
            self.dataset.prompt_version,
            self.dataset.review_artifact_hash,
        )
        actual = (
            self.report.commit_sha,
            self.report.controller_fingerprint,
            self.report.configuration_fingerprint,
            self.report.prompt_version,
            self.report.review_artifact_hash,
        )
        if actual != expected:
            raise ValueError(
                "Shadow Gate report does not bind its dataset"
            )
        return self

    @classmethod
    def from_result(
        cls,
        *,
        source_state: GitSourceState,
        dataset: ShadowGateDataset,
        report: ShadowGateReport,
    ) -> "ShadowGateEvidenceArtifact":
        return cls(
            source_state=source_state,
            generated_at=dataset.collected_at,
            dataset=ShadowGateDatasetSummary.from_dataset(dataset),
            report=report,
        )


__all__ = [
    "SHADOW_GATE_EVIDENCE_VERSION",
    "ShadowGateDatasetSummary",
    "ShadowGateEvidenceArtifact",
]
