from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas.chat import UserInput
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.certification_contracts import (
    AGENT_CERTIFICATION_CONTRACT_VERSION,
)
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.shadow_decision_diff import (
    ShadowDecisionDiffer,
)
from app.services.agent_core.shadow_enrollment import (
    build_shadow_enrollment,
    is_current_shadow_enrollment,
    prepare_shadow_enrollment,
)
from app.services.agent_core.shadow_gate_dataset_builder import (
    ShadowGateDatasetBuilder,
)
from app.services.agent_core.shadow_gate_evaluator import (
    ShadowGateEvaluator,
)
from app.services.agent_core.shadow_gate_evidence import (
    ShadowGateEvidenceArtifact,
)
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateRawTurn,
    ShadowGateRawWindow,
    ShadowGateReadRequest,
    ShadowLegacyTerminal,
)
from app.services.agent_core.shadow_observation_contracts import (
    ShadowObservation,
)
from app.services.agent_core.shadow_recovery import (
    ShadowRecoveryProjector,
)
from app.services.agent_core.shadow_recovery_contracts import (
    PendingShadowEnrollment,
)
from app.services.agent_core.release_identity import (
    AgentReleaseIdentityError,
)
from app.services.agent_core.shadow_review_artifact import (
    ShadowReviewArtifactLoader,
)
from app.services.agent_core.shadow_review_queue import (
    ShadowReviewQueueBuilder,
)


START = datetime(2026, 7, 27, tzinfo=timezone.utc)
END = START + timedelta(days=3)
CONTROLLER_FP = current_controller_fingerprint()
CONFIG_FP = "a" * 64
SOURCE_COMMIT = "c" * 40


def _read_request(*, collected_at: datetime) -> ShadowGateReadRequest:
    return ShadowGateReadRequest(
        commit_sha=SOURCE_COMMIT,
        controller_fingerprint=CONTROLLER_FP,
        configuration_fingerprint=CONFIG_FP,
        prompt_version="agent-controller-v1",
        window_started_at=START,
        window_ended_at=END,
        collected_at=collected_at,
    )


def _observation(key: str) -> ShadowObservation:
    return ShadowObservation(
        id=uuid4(),
        observation_key=key,
        user_id=uuid4(),
        thread_id=uuid4(),
        request_id="request-1",
        journal_sequence_watermark=1,
        model_id=uuid4(),
        configuration_fingerprint=CONFIG_FP,
        source_commit_sha=SOURCE_COMMIT,
        controller_fingerprint=CONTROLLER_FP,
        agent_core_contract_version="agent-core-v1",
        certification_contract_version=(
            AGENT_CERTIFICATION_CONTRACT_VERSION
        ),
        prompt_version="agent-controller-v1",
        input_evidence_hash="e" * 64,
        controller_status="shadow_valid",
        output_mode="capability_proposals",
        valid=True,
        would_execute=True,
        side_effect_count=0,
        latency_ms=17,
        proposal_summary={
            "mode": "capability_proposals",
            "capabilities": [{"name": "search_memory"}],
        },
        plan_summary={
            "route_type": "tool",
            "intent": "memory_read",
            "actions": [{"capability": "search_memory"}],
        },
        checks=[],
        violation_codes=[],
        error_hashes=[],
        created_at=START + timedelta(seconds=1),
    )


class ShadowGateDataTests(unittest.TestCase):
    def test_enrollment_preparation_is_shadow_only(self) -> None:
        user_input = UserInput(
            content="hello",
            user_id=uuid4(),
            thread_id=uuid4(),
            request_id="request-mode",
            model_uuid=str(uuid4()),
        )
        calls: list[str | None] = []

        def resolve(value: str | None) -> str:
            calls.append(value)
            return "resolved-controller"

        for mode in ("off", "live"):
            prepared = prepare_shadow_enrollment(
                user_input,
                mode=mode,
                model_resolver=resolve,
                source_commit_sha=None,
            )
            self.assertIsNone(prepared.enrollment)
            self.assertIsNone(prepared.resolved_model_name)
        self.assertFalse(calls)

        shadow = prepare_shadow_enrollment(
            user_input,
            mode="shadow",
            model_resolver=resolve,
            source_commit_sha=SOURCE_COMMIT,
        )
        self.assertEqual(shadow.resolved_model_name, "resolved-controller")
        self.assertEqual(
            shadow.enrollment.model_name,
            "resolved-controller",
        )
        self.assertEqual(len(calls), 1)
        with self.assertRaises(AgentReleaseIdentityError):
            prepare_shadow_enrollment(
                user_input,
                mode="shadow",
                model_resolver=resolve,
                source_commit_sha=None,
            )

    def test_enrollment_and_recovery_reconstruct_exact_command(self) -> None:
        user_input = UserInput(
            content="What did I say?",
            user_id=uuid4(),
            thread_id=uuid4(),
            request_id="request-1",
            model_uuid=str(uuid4()),
            timezone="Asia/Shanghai",
        )
        enrollment = build_shadow_enrollment(
            user_input,
            resolved_model_name="fixture-controller",
            source_commit_sha=SOURCE_COMMIT,
        )
        self.assertTrue(
            is_current_shadow_enrollment(
                enrollment,
                source_commit_sha=SOURCE_COMMIT,
            )
        )
        pending = PendingShadowEnrollment(
            user_id=user_input.user_id,
            thread_id=user_input.thread_id,
            request_id=user_input.request_id,
            content=user_input.content,
            journal_sequence_watermark=7,
            enrollment=enrollment,
        )

        command = ShadowRecoveryProjector().project(pending)

        self.assertEqual(command.user_input.content, user_input.content)
        self.assertEqual(command.journal_sequence_watermark, 7)
        self.assertEqual(
            command.controller_fingerprint,
            CONTROLLER_FP,
        )

    def test_difference_and_delivery_grace_are_deterministic(self) -> None:
        key = "1" * 64
        turn = ShadowGateRawTurn(
            observation_key=key,
            enrolled_at=START,
            journal_sequence_watermark=1,
            terminal_events=[
                ShadowLegacyTerminal(
                    event_type="assistant_published",
                    sequence_no=2,
                    summary={
                        "terminal_kind": "assistant_published",
                        "runtime_trace": {
                            "route_type": "direct",
                            "intent": "plain_chat",
                        },
                        "operations": [],
                    },
                )
            ],
            observation=_observation(key),
        )
        difference = ShadowDecisionDiffer().compare(turn)
        self.assertEqual(
            difference.kind,
            "decision_mode+intent+operations+route_type",
        )
        self.assertEqual(len(difference.fingerprint or ""), 64)
        self.assertEqual(
            difference.new_signature.operations,
            ["search_memory"],
        )
        self.assertEqual(
            difference.legacy_signature.operations,
            [],
        )

        pending_raw = ShadowGateRawWindow(
            request=_read_request(collected_at=END),
            turns=[
                turn,
                ShadowGateRawTurn(
                    observation_key="2" * 64,
                    enrolled_at=START,
                    journal_sequence_watermark=3,
                ),
            ],
        )
        pending = ShadowGateDatasetBuilder().build(pending_raw)
        self.assertEqual(pending.coverage.pending_within_grace, 1)
        self.assertEqual(pending.coverage.missing_after_grace, 0)

        expired_raw = pending_raw.model_copy(
            update={
                "request": _read_request(
                    collected_at=END + timedelta(minutes=5)
                )
            }
        )
        expired = ShadowGateDatasetBuilder().build(expired_raw)
        self.assertEqual(expired.coverage.pending_within_grace, 0)
        self.assertEqual(expired.coverage.missing_after_grace, 1)

    def test_review_artifact_is_bound_to_difference_fingerprint(self) -> None:
        key = "1" * 64
        turn = ShadowGateRawTurn(
            observation_key=key,
            enrolled_at=START,
            journal_sequence_watermark=1,
            terminal_events=[
                ShadowLegacyTerminal(
                    event_type="assistant_published",
                    sequence_no=2,
                    summary={
                        "terminal_kind": "assistant_published",
                        "runtime_trace": {},
                        "operations": [],
                    },
                )
            ],
            observation=_observation(key),
        )
        difference = ShadowDecisionDiffer().compare(turn)
        request = _read_request(
            collected_at=END + timedelta(minutes=5)
        )
        payload = {
            "artifact_version": "shadow-decision-review-v1",
            "commit_sha": request.commit_sha,
            "controller_fingerprint": request.controller_fingerprint,
            "configuration_fingerprint": (
                request.configuration_fingerprint
            ),
            "prompt_version": request.prompt_version,
            "window_started_at": request.window_started_at.isoformat(),
            "window_ended_at": request.window_ended_at.isoformat(),
            "reviews": [
                {
                    "observation_key": key,
                    "review": {
                        "classification": "expected_improvement",
                        "severity": "P2",
                        "explained": True,
                        "difference_fingerprint": (
                            difference.fingerprint
                        ),
                        "reviewer_id": "release-reviewer",
                        "reviewed_at": END.isoformat(),
                        "reason_codes": [
                            "expected.routing_improvement"
                        ],
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            loaded = ShadowReviewArtifactLoader().load(
                path,
                request=request,
            )

        dataset = ShadowGateDatasetBuilder().build(
            ShadowGateRawWindow(request=request, turns=[turn]),
            reviews=loaded,
        )
        self.assertEqual(
            dataset.observations[0].review.reviewer_id,
            "release-reviewer",
        )
        self.assertEqual(len(dataset.review_artifact_hash or ""), 64)

    def test_review_queue_contains_only_allowlisted_signatures(self) -> None:
        key = "3" * 64
        turn = ShadowGateRawTurn(
            observation_key=key,
            enrolled_at=START,
            journal_sequence_watermark=1,
            terminal_events=[
                ShadowLegacyTerminal(
                    event_type="assistant_published",
                    sequence_no=2,
                    summary={
                        "terminal_kind": "assistant_published",
                        "runtime_trace": {
                            "route_type": "direct",
                            "intent": "plain_chat",
                        },
                        "operations": [],
                        "raw_user_message": "private-user-content",
                    },
                )
            ],
            observation=_observation(key),
        )
        raw = ShadowGateRawWindow(
            request=_read_request(
                collected_at=END + timedelta(minutes=5)
            ),
            turns=[
                turn,
                ShadowGateRawTurn(
                    observation_key="4" * 64,
                    enrolled_at=START,
                    journal_sequence_watermark=3,
                ),
            ],
        )
        artifact = ShadowReviewQueueBuilder().build(
            raw,
            source_state=GitSourceState(
                commit_sha="c" * 40,
                dirty_worktree=False,
            ),
        )
        self.assertEqual(len(artifact.candidates), 1)
        self.assertEqual(
            artifact.candidates[0].new_signature.operations,
            ["search_memory"],
        )
        rendered = artifact.model_dump_json()
        self.assertNotIn("private-user-content", rendered)
        self.assertNotIn("arguments", rendered)
        self.assertNotIn("Provider output", rendered)

    def test_shadow_gate_evidence_binds_clean_source_and_report(self) -> None:
        key = "5" * 64
        turn = ShadowGateRawTurn(
            observation_key=key,
            enrolled_at=START,
            journal_sequence_watermark=1,
            terminal_events=[
                ShadowLegacyTerminal(
                    event_type="assistant_published",
                    sequence_no=2,
                    summary={
                        "terminal_kind": "assistant_published",
                        "runtime_trace": {},
                        "operations": ["search_memory"],
                    },
                )
            ],
            observation=_observation(key),
        )
        dataset = ShadowGateDatasetBuilder().build(
            ShadowGateRawWindow(
                request=_read_request(
                    collected_at=END + timedelta(minutes=5)
                ),
                turns=[turn],
            )
        )
        report = ShadowGateEvaluator().evaluate(dataset)
        artifact = ShadowGateEvidenceArtifact.from_result(
            source_state=GitSourceState(
                commit_sha="c" * 40,
                dirty_worktree=False,
            ),
            dataset=dataset,
            report=report,
        )
        self.assertEqual(
            artifact.artifact_version,
            "shadow-gate-evidence-v1",
        )
        self.assertEqual(
            artifact.source_state.commit_sha,
            artifact.report.commit_sha,
        )
        self.assertFalse(
            hasattr(artifact.dataset, "observations")
        )


if __name__ == "__main__":
    unittest.main()
