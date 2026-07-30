from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.shadow_observation_contracts import (
    ShadowControllerResultStatus,
)


ShadowGateStatus = Literal["passed", "failed", "blocked"]
ShadowReviewSeverity = Literal["P0", "P1", "P2", "P3"]
ShadowReviewClassification = Literal[
    "expected_improvement",
    "acceptable_difference",
    "new_regression",
    "needs_investigation",
]


class ShadowDecisionReview(AgentCoreModel):
    classification: ShadowReviewClassification
    severity: ShadowReviewSeverity
    explained: bool
    difference_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    reviewer_id: str = Field(pattern="^[a-zA-Z0-9_.@-]{1,128}$")
    reviewed_at: datetime
    reason_codes: list[str] = Field(min_length=1, max_length=16)

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, value: list[str]) -> list[str]:
        invalid = [
            item
            for item in value
            if re.fullmatch(r"[a-z0-9_.-]{1,128}", item) is None
        ]
        if invalid:
            raise ValueError(
                "Shadow review reasons must be stable non-content codes"
            )
        return value

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_review_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Shadow review time must be timezone-aware")
        return value


class ShadowCoverageSnapshot(AgentCoreModel):
    eligible: int = Field(ge=0)
    observed: int = Field(ge=0)
    pending_within_grace: int = Field(ge=0)
    missing_after_grace: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_partition(self) -> "ShadowCoverageSnapshot":
        if self.eligible != (
            self.observed
            + self.pending_within_grace
            + self.missing_after_grace
        ):
            raise ValueError(
                "Shadow coverage must partition every eligible enrollment"
            )
        return self


class ShadowGateObservation(AgentCoreModel):
    observation_key: str = Field(pattern="^[0-9a-f]{64}$")
    created_at: datetime
    source_commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    configuration_fingerprint: str = Field(
        pattern="^[0-9a-f]{64}$"
    )
    controller_status: ShadowControllerResultStatus
    journal_terminal_count: int = Field(ge=0)
    journal_watermark_match: bool = True
    audit_receipt_count: int = Field(ge=0)
    system_field_violation_count: int = Field(default=0, ge=0)
    publication_violation_count: int = Field(default=0, ge=0)
    memory_high_risk_event_count: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    difference_kind: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    difference_fingerprint: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{64}$",
    )
    review: ShadowDecisionReview | None = None

    @model_validator(mode="after")
    def validate_review_scope(self) -> "ShadowGateObservation":
        if self.difference_kind is None and self.review is not None:
            raise ValueError(
                "a review requires one detected decision difference"
            )
        if (
            self.difference_kind is None
            and self.difference_fingerprint is not None
        ):
            raise ValueError(
                "a difference fingerprint requires a detected difference"
            )
        if (
            self.difference_kind is not None
            and self.difference_fingerprint is None
        ):
            raise ValueError(
                "a detected difference requires its fingerprint"
            )
        if (
            self.review is not None
            and self.review.difference_fingerprint
            != self.difference_fingerprint
        ):
            raise ValueError(
                "review does not bind the current decision difference"
            )
        return self


class ShadowGateDataset(AgentCoreModel):
    commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    configuration_fingerprint: str = Field(
        pattern="^[0-9a-f]{64}$"
    )
    prompt_version: str = Field(min_length=1, max_length=64)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    window_started_at: datetime
    window_ended_at: datetime
    collected_at: datetime
    grace_period_seconds: int = Field(default=300, ge=1, le=86_400)
    review_artifact_hash: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{64}$",
    )
    coverage: ShadowCoverageSnapshot
    observations: list[ShadowGateObservation] = Field(
        default_factory=list,
        max_length=100_000,
    )

    @model_validator(mode="after")
    def validate_window(self) -> "ShadowGateDataset":
        for value in (
            self.window_started_at,
            self.window_ended_at,
            self.collected_at,
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    "Shadow dataset timestamps must be timezone-aware"
                )
        if self.window_ended_at <= self.window_started_at:
            raise ValueError("Shadow window end must follow its start")
        return self


class ShadowGateReport(AgentCoreModel):
    status: ShadowGateStatus
    commit_sha: str
    controller_fingerprint: str
    configuration_fingerprint: str
    prompt_version: str
    sample_count: int = Field(ge=0)
    natural_day_count: int = Field(ge=0)
    max_consecutive_natural_days: int = Field(ge=0)
    difference_count: int = Field(ge=0)
    reviewed_difference_count: int = Field(ge=0)
    audit_receipt_count: int = Field(ge=0)
    pending_within_grace: int = Field(ge=0)
    missing_after_grace: int = Field(ge=0)
    latency_p50_ms: int = Field(ge=0)
    latency_p95_ms: int = Field(ge=0)
    review_artifact_hash: str | None = None
    reasons: list[str] = Field(default_factory=list)
    error_observation_keys: list[str] = Field(default_factory=list)
    blocked_observation_keys: list[str] = Field(default_factory=list)


__all__ = [
    "ShadowDecisionReview",
    "ShadowCoverageSnapshot",
    "ShadowGateDataset",
    "ShadowGateObservation",
    "ShadowGateReport",
    "ShadowGateStatus",
]
