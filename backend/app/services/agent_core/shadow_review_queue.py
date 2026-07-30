from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.shadow_decision_diff import (
    ShadowDecisionDiffer,
    ShadowDecisionSignature,
)
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateRawWindow,
)


SHADOW_REVIEW_QUEUE_VERSION = "shadow-review-queue-v1"


class ShadowReviewCandidate(AgentCoreModel):
    observation_key: str = Field(pattern="^[0-9a-f]{64}$")
    difference_kind: str = Field(min_length=1, max_length=128)
    difference_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    new_signature: ShadowDecisionSignature
    legacy_signature: ShadowDecisionSignature


class ShadowReviewQueueArtifact(AgentCoreModel):
    artifact_version: Literal["shadow-review-queue-v1"] = (
        SHADOW_REVIEW_QUEUE_VERSION
    )
    source_state: GitSourceState
    generated_at: datetime
    commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    configuration_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=64)
    window_started_at: datetime
    window_ended_at: datetime
    candidates: list[ShadowReviewCandidate] = Field(
        default_factory=list,
        max_length=100_000,
    )

    @model_validator(mode="after")
    def validate_bindings(self) -> "ShadowReviewQueueArtifact":
        for value in (
            self.generated_at,
            self.window_started_at,
            self.window_ended_at,
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    "Shadow review queue times must be timezone-aware"
                )
        if self.window_ended_at <= self.window_started_at:
            raise ValueError(
                "Shadow review queue end must follow its start"
            )
        if self.generated_at < self.window_ended_at:
            raise ValueError(
                "Shadow review queue requires a closed window"
            )
        if self.source_state.dirty_worktree:
            raise ValueError(
                "Shadow review queue requires clean source"
            )
        if self.commit_sha != self.source_state.commit_sha:
            raise ValueError(
                "Shadow review queue source commit mismatch"
            )
        keys = [item.observation_key for item in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Shadow review queue contains duplicate observations"
            )
        return self


class ShadowReviewQueueBuilder:
    """Project safe decision differences without I/O or review decisions."""

    def __init__(
        self,
        *,
        differ: ShadowDecisionDiffer | None = None,
    ) -> None:
        self._differ = differ or ShadowDecisionDiffer()

    def build(
        self,
        raw: ShadowGateRawWindow,
        *,
        source_state: GitSourceState,
    ) -> ShadowReviewQueueArtifact:
        request = raw.request
        candidates: list[ShadowReviewCandidate] = []
        for turn in raw.turns:
            difference = self._differ.compare(turn)
            if difference.kind is None:
                continue
            candidates.append(
                ShadowReviewCandidate(
                    observation_key=turn.observation_key,
                    difference_kind=difference.kind,
                    difference_fingerprint=difference.fingerprint,
                    new_signature=difference.new_signature,
                    legacy_signature=difference.legacy_signature,
                )
            )
        return ShadowReviewQueueArtifact(
            source_state=source_state,
            generated_at=request.collected_at,
            commit_sha=request.commit_sha,
            controller_fingerprint=request.controller_fingerprint,
            configuration_fingerprint=request.configuration_fingerprint,
            prompt_version=request.prompt_version,
            window_started_at=request.window_started_at,
            window_ended_at=request.window_ended_at,
            candidates=candidates,
        )


__all__ = [
    "SHADOW_REVIEW_QUEUE_VERSION",
    "ShadowReviewCandidate",
    "ShadowReviewQueueArtifact",
    "ShadowReviewQueueBuilder",
]
