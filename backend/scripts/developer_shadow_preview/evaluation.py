from __future__ import annotations

import json
import uuid

from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.prompt_composer import CONTROLLER_PROMPT_VERSION
from app.services.agent_core.shadow_decision_diff import ShadowDecisionDiffer
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateRawWindow,
)
from app.services.agent_core.shadow_observation_key import (
    shadow_observation_key_from_identity,
)
from app.services.agent_core.shadow_review_queue import (
    ShadowReviewQueueArtifact,
    ShadowReviewQueueBuilder,
)
from scripts.developer_shadow_preview.contracts import (
    DeveloperShadowCoverage,
)


class DeveloperShadowEvaluationError(RuntimeError):
    """Fail-closed pure evaluation error with a stable reason code."""


class DeveloperShadowPreviewEvaluator:
    """Evaluate durable preview facts without database or network access."""

    def select_request_scope(
        self,
        raw: ShadowGateRawWindow,
        *,
        request_ids: list[str],
        thread_id: uuid.UUID,
        controller_fingerprint: str,
    ) -> ShadowGateRawWindow:
        expected_keys = {
            shadow_observation_key_from_identity(
                thread_id=thread_id,
                request_id=request_id,
                controller_fingerprint=controller_fingerprint,
            )
            for request_id in request_ids
        }
        selected = [
            turn
            for turn in raw.turns
            if turn.observation_key in expected_keys
        ]
        if (
            len(selected) != len(expected_keys)
            or {turn.observation_key for turn in selected} != expected_keys
        ):
            raise DeveloperShadowEvaluationError(
                "shadow_enrollment_set_mismatch"
            )
        return raw.model_copy(update={"turns": selected})

    def validate_window(
        self,
        raw: ShadowGateRawWindow,
        *,
        request_ids: list[str],
        thread_id: uuid.UUID,
        model_id: uuid.UUID,
        admission: AgentModeAdmission,
    ) -> DeveloperShadowCoverage:
        expected_keys = {
            shadow_observation_key_from_identity(
                thread_id=thread_id,
                request_id=request_id,
                controller_fingerprint=admission.controller_fingerprint,
            )
            for request_id in request_ids
        }
        if {turn.observation_key for turn in raw.turns} != expected_keys:
            raise DeveloperShadowEvaluationError(
                "shadow_enrollment_set_mismatch"
            )
        valid_count = 0
        terminal_count = 0
        watermark_count = 0
        violation_count = 0
        for turn in raw.turns:
            observation = turn.observation
            if observation is None:
                raise DeveloperShadowEvaluationError(
                    "shadow_observation_missing"
                )
            if (
                observation.model_id != model_id
                or str(observation.certification_id)
                != admission.certification_id
                or observation.configuration_fingerprint
                != admission.configuration_fingerprint
                or observation.source_commit_sha
                != admission.source_commit_sha
                or observation.controller_fingerprint
                != admission.controller_fingerprint
                or observation.prompt_version != CONTROLLER_PROMPT_VERSION
            ):
                raise DeveloperShadowEvaluationError(
                    "shadow_observation_binding_mismatch"
                )
            if (
                observation.controller_status != "shadow_valid"
                or observation.valid is not True
            ):
                raise DeveloperShadowEvaluationError(
                    "shadow_observation_not_valid"
                )
            valid_count += 1
            violation_count += len(observation.violation_codes)
            if (
                len(turn.terminal_events) != 1
                or turn.terminal_events[0].event_type
                != "assistant_published"
            ):
                raise DeveloperShadowEvaluationError(
                    "shadow_terminal_event_invalid"
                )
            terminal_count += 1
            if (
                observation.journal_sequence_watermark
                != turn.journal_sequence_watermark
            ):
                raise DeveloperShadowEvaluationError(
                    "shadow_journal_watermark_mismatch"
                )
            watermark_count += 1
            if turn.audit_receipt_count:
                raise DeveloperShadowEvaluationError(
                    "shadow_audit_receipt_detected"
                )
        return DeveloperShadowCoverage(
            requested=len(request_ids),
            accepted=len(request_ids),
            enrolled=len(raw.turns),
            observed=sum(
                turn.observation is not None for turn in raw.turns
            ),
            shadow_valid=valid_count,
            terminal=terminal_count,
            watermark_match=watermark_count,
            violation_count=violation_count,
        )

    def build_review_queue(
        self,
        raw: ShadowGateRawWindow,
        *,
        source_state: GitSourceState,
    ) -> tuple[ShadowReviewQueueArtifact, int]:
        artifact = ShadowReviewQueueBuilder().build(
            raw,
            source_state=source_state,
        )
        differ = ShadowDecisionDiffer()
        difference_count = sum(
            differ.compare(turn).kind is not None for turn in raw.turns
        )
        if len(artifact.candidates) != difference_count:
            raise DeveloperShadowEvaluationError(
                "shadow_review_queue_incomplete"
            )
        return artifact, difference_count

    @staticmethod
    def assert_no_raw_input_leakage(
        *,
        prompts: list[str],
        payloads: list[object],
    ) -> None:
        rendered = json.dumps(
            [
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else item
                for item in payloads
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        if any(prompt in rendered for prompt in prompts):
            raise DeveloperShadowEvaluationError(
                "raw_input_leaked_into_artifact"
            )


__all__ = [
    "DeveloperShadowEvaluationError",
    "DeveloperShadowPreviewEvaluator",
]
