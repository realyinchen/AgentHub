from __future__ import annotations

from datetime import timedelta

from app.services.agent_core.shadow_decision_diff import (
    ShadowDecisionDiffer,
)
from app.services.agent_core.shadow_gate_contracts import (
    ShadowCoverageSnapshot,
    ShadowGateDataset,
    ShadowGateObservation,
)
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateRawWindow,
)
from app.services.agent_core.shadow_review_artifact import (
    LoadedShadowReviewArtifact,
)


class ShadowGateDatasetBuilder:
    """Merge raw durable evidence and an optional bound review artifact."""

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
        reviews: LoadedShadowReviewArtifact | None = None,
    ) -> ShadowGateDataset:
        request = raw.request
        if reviews is not None:
            artifact = reviews.artifact
            if (
                artifact.commit_sha != request.commit_sha
                or artifact.controller_fingerprint
                != request.controller_fingerprint
                or artifact.configuration_fingerprint
                != request.configuration_fingerprint
                or artifact.prompt_version != request.prompt_version
                or artifact.window_started_at
                != request.window_started_at
                or artifact.window_ended_at != request.window_ended_at
            ):
                raise ValueError(
                    "Shadow review artifact does not bind the raw window"
                )
        review_by_key = (
            {
                item.observation_key: item.review
                for item in reviews.artifact.reviews
            }
            if reviews is not None
            else {}
        )
        observations: list[ShadowGateObservation] = []
        difference_keys: set[str] = set()
        for turn in raw.turns:
            observation = turn.observation
            if observation is None:
                continue
            difference = self._differ.compare(turn)
            review = review_by_key.get(turn.observation_key)
            if difference.kind is not None:
                difference_keys.add(turn.observation_key)
                if (
                    review is not None
                    and review.difference_fingerprint
                    != difference.fingerprint
                ):
                    raise ValueError(
                        "stale Shadow review difference fingerprint"
                    )
            elif review is not None:
                raise ValueError(
                    "orphan Shadow review has no current difference"
                )
            violation_codes = set(observation.violation_codes)
            observations.append(
                ShadowGateObservation(
                    observation_key=turn.observation_key,
                    created_at=turn.enrolled_at,
                    source_commit_sha=(
                        observation.source_commit_sha or "0" * 40
                    ),
                    controller_fingerprint=(
                        observation.controller_fingerprint
                    ),
                    configuration_fingerprint=(
                        observation.configuration_fingerprint
                        or "0" * 64
                    ),
                    controller_status=observation.controller_status,
                    journal_terminal_count=len(turn.terminal_events),
                    journal_watermark_match=(
                        observation.journal_sequence_watermark
                        == turn.journal_sequence_watermark
                    ),
                    audit_receipt_count=turn.audit_receipt_count,
                    system_field_violation_count=int(
                        "system_owned_field" in violation_codes
                    ),
                    publication_violation_count=int(
                        "unreceipted_success_claim"
                        in violation_codes
                    ),
                    memory_high_risk_event_count=int(
                        "memory_precommit_not_ready"
                        in violation_codes
                    ),
                    latency_ms=observation.latency_ms,
                    difference_kind=difference.kind,
                    difference_fingerprint=difference.fingerprint,
                    review=review,
                )
            )
        orphan_reviews = set(review_by_key).difference(difference_keys)
        if orphan_reviews:
            raise ValueError(
                "Shadow review artifact contains orphan observation keys"
            )
        observed = len(observations)
        missing = len(raw.turns) - observed
        grace_deadline = request.window_ended_at + timedelta(
            seconds=request.grace_period_seconds
        )
        pending = (
            missing
            if request.collected_at < grace_deadline
            else 0
        )
        expired = missing - pending
        return ShadowGateDataset(
            commit_sha=request.commit_sha,
            controller_fingerprint=request.controller_fingerprint,
            configuration_fingerprint=(
                request.configuration_fingerprint
            ),
            prompt_version=request.prompt_version,
            timezone=request.timezone,
            window_started_at=request.window_started_at,
            window_ended_at=request.window_ended_at,
            collected_at=request.collected_at,
            grace_period_seconds=request.grace_period_seconds,
            review_artifact_hash=(
                reviews.sha256 if reviews is not None else None
            ),
            coverage=ShadowCoverageSnapshot(
                eligible=len(raw.turns),
                observed=observed,
                pending_within_grace=pending,
                missing_after_grace=expired,
            ),
            observations=observations,
        )


__all__ = ["ShadowGateDatasetBuilder"]
