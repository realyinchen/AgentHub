from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.shadow_gate_contracts import (
    ShadowDecisionReview,
)
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateReadRequest,
)


SHADOW_REVIEW_ARTIFACT_VERSION = "shadow-decision-review-v1"


class ShadowReviewEntry(AgentCoreModel):
    observation_key: str = Field(pattern="^[0-9a-f]{64}$")
    review: ShadowDecisionReview


class ShadowReviewArtifact(AgentCoreModel):
    artifact_version: Literal["shadow-decision-review-v1"] = (
        SHADOW_REVIEW_ARTIFACT_VERSION
    )
    commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    configuration_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=64)
    window_started_at: datetime
    window_ended_at: datetime
    reviews: list[ShadowReviewEntry] = Field(
        default_factory=list,
        max_length=100_000,
    )

    @model_validator(mode="after")
    def validate_unique_reviews(self) -> "ShadowReviewArtifact":
        for value in (
            self.window_started_at,
            self.window_ended_at,
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    "Shadow review window must be timezone-aware"
                )
        if self.window_ended_at <= self.window_started_at:
            raise ValueError(
                "Shadow review window end must follow its start"
            )
        keys = [item.observation_key for item in self.reviews]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate Shadow review observation keys")
        return self


class LoadedShadowReviewArtifact(AgentCoreModel):
    artifact: ShadowReviewArtifact
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class ShadowReviewArtifactLoader:
    """Load and bind one release review artifact to an exact window."""

    def load(
        self,
        path: str | Path,
        *,
        request: ShadowGateReadRequest,
    ) -> LoadedShadowReviewArtifact:
        raw = Path(path).read_bytes()
        artifact = ShadowReviewArtifact.model_validate(
            json.loads(raw.decode("utf-8"))
        )
        expected = (
            request.commit_sha,
            request.controller_fingerprint,
            request.configuration_fingerprint,
            request.prompt_version,
            request.window_started_at,
            request.window_ended_at,
        )
        actual = (
            artifact.commit_sha,
            artifact.controller_fingerprint,
            artifact.configuration_fingerprint,
            artifact.prompt_version,
            artifact.window_started_at,
            artifact.window_ended_at,
        )
        if actual != expected:
            raise ValueError(
                "Shadow review artifact does not bind the requested window"
            )
        return LoadedShadowReviewArtifact(
            artifact=artifact,
            sha256=hashlib.sha256(raw).hexdigest(),
        )


__all__ = [
    "LoadedShadowReviewArtifact",
    "SHADOW_REVIEW_ARTIFACT_VERSION",
    "ShadowReviewArtifact",
    "ShadowReviewArtifactLoader",
    "ShadowReviewEntry",
]
