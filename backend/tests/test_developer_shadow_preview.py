from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from app.services.agent_core.controller_golden_contracts import (
    ControllerGoldenReport,
)
from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.prompt_composer import CONTROLLER_PROMPT_VERSION
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateRawTurn,
    ShadowGateRawWindow,
    ShadowGateReadRequest,
)
from app.services.agent_core.shadow_observation_key import (
    shadow_observation_key_from_identity,
)
from scripts.developer_shadow_preview.contracts import (
    DeveloperShadowBusinessWrites,
    DeveloperShadowCleanup,
    DeveloperShadowCoverage,
    DeveloperShadowPreviewArtifact,
    DeveloperShadowPreviewCommand,
)
from scripts.developer_shadow_preview.admission import (
    DeveloperPreviewAdmissionError,
    DeveloperPreviewAdmissionPolicy,
    DeveloperShadowAdmissionCandidate,
    DeveloperShadowModelProfile,
)
from scripts.developer_shadow_preview.evaluation import (
    DeveloperShadowEvaluationError,
    DeveloperShadowPreviewEvaluator,
)
from scripts.developer_shadow_preview.http_client import (
    DeveloperShadowHttpError,
    DeveloperShadowHttpClient,
)
from scripts.developer_shadow_preview.source import (
    DeveloperShadowSourceError,
    DeveloperShadowSourceVerifier,
)
from scripts.developer_shadow_preview.window import (
    DeveloperShadowWindowClock,
)


COMMIT = "c" * 40
CONFIGURATION = "a" * 64
CONTROLLER = "b" * 64
DATASET_HASH = "d" * 64
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _golden(model_id: uuid.UUID) -> ControllerGoldenReport:
    return ControllerGoldenReport(
        status="passed",
        live_model_evidence=True,
        commit_sha=COMMIT,
        source_dirty_worktree=False,
        generated_at=datetime.now(timezone.utc),
        model_id=model_id,
        certification_id=str(uuid.uuid4()),
        configuration_fingerprint=CONFIGURATION,
        controller_fingerprint=CONTROLLER,
        prompt_version=CONTROLLER_PROMPT_VERSION,
        dataset_version="controller-golden-v1",
        dataset_hash=DATASET_HASH,
        sample_count=26,
        passed_count=26,
        critical_count=26,
        critical_passed=26,
        safety_count=4,
        safety_passed=4,
        explicit_tool_count=13,
        explicit_tool_passed=13,
        simple_direct_count=5,
        simple_tool_trigger_count=0,
        total_controller_calls=26,
        total_runtime_calls=0,
    )


def _admission_candidate(
    golden: ControllerGoldenReport,
    *,
    configured_thinking: bool = False,
    profile: DeveloperShadowModelProfile | None = None,
) -> DeveloperShadowAdmissionCandidate:
    return DeveloperShadowAdmissionCandidate(
        admission=AgentModeAdmission(
            admitted=True,
            certification_id=golden.certification_id,
            reason=None,
            configuration_fingerprint=golden.configuration_fingerprint,
            controller_fingerprint=golden.controller_fingerprint,
            source_commit_sha=golden.commit_sha,
        ),
        model_profile=profile
        or DeveloperShadowModelProfile(
            model_type="llm",
            configured_thinking=configured_thinking,
            is_active=True,
        ),
    )


def _artifact(**updates) -> DeveloperShadowPreviewArtifact:
    now = datetime.now(timezone.utc)
    values = {
        "generated_at": now,
        "source_state": GitSourceState(
            commit_sha=COMMIT,
            dirty_worktree=False,
        ),
        "source_commit_sha": COMMIT,
        "remote_ref": "origin/dev",
        "remote_commit_sha": COMMIT,
        "model_id": uuid.uuid4(),
        "admission_profile": "developer_preview",
        "configured_thinking": True,
        "certification_id": uuid.uuid4(),
        "configuration_fingerprint": CONFIGURATION,
        "controller_fingerprint": CONTROLLER,
        "prompt_version": CONTROLLER_PROMPT_VERSION,
        "golden_artifact_sha256": "e" * 64,
        "review_queue_sha256": "f" * 64,
        "base_url": "http://127.0.0.1:8081",
        "window_started_at": now - timedelta(minutes=1),
        "window_ended_at": now,
        "coverage": DeveloperShadowCoverage(
            requested=20,
            accepted=20,
            enrolled=20,
            observed=20,
            shadow_valid=20,
            terminal=20,
            watermark_match=20,
            violation_count=0,
        ),
        "business_writes": DeveloperShadowBusinessWrites(
            memory_events=0,
            task_states=0,
            task_plan_versions=0,
            research_runs=0,
            shadow_audit_receipts=0,
            legacy_request_receipts=3,
        ),
        "response_modes": {"legacy_runtime": 20},
        "difference_count": 2,
        "review_queue_candidate_count": 2,
        "cleanup": DeveloperShadowCleanup(
            users=0,
            conversations=0,
            conversation_events=0,
            shadow_observations=0,
            memory_events=0,
            task_states=0,
            task_plan_versions=0,
            research_runs=0,
            request_receipts=0,
        ),
    }
    values.update(updates)
    return DeveloperShadowPreviewArtifact(**values)


class DeveloperShadowPreviewContractTests(unittest.TestCase):
    def test_preview_modules_preserve_unix_dependency_boundaries(self) -> None:
        sources = {
            name: (BACKEND_DIR / path).read_text(encoding="utf-8")
            for name, path in {
                "cli": "scripts/verify_developer_shadow_preview.py",
                "source": "scripts/developer_shadow_preview/source.py",
                "http": "scripts/developer_shadow_preview/http_client.py",
                "repository": "scripts/developer_shadow_preview/repository.py",
                "evaluation": "scripts/developer_shadow_preview/evaluation.py",
                "service": "scripts/developer_shadow_preview/service.py",
                "admission": "scripts/developer_shadow_preview/admission.py",
                "window": "scripts/developer_shadow_preview/window.py",
            }.items()
        }
        for forbidden in ("sqlalchemy", "httpx", "subprocess"):
            self.assertNotIn(forbidden, sources["cli"])
            self.assertNotIn(forbidden, sources["service"])
        self.assertNotIn("sqlalchemy", sources["source"])
        self.assertNotIn("httpx", sources["source"])
        self.assertNotIn("sqlalchemy", sources["http"])
        self.assertNotIn("subprocess", sources["http"])
        self.assertNotIn("httpx", sources["repository"])
        self.assertNotIn("subprocess", sources["repository"])
        self.assertNotIn("sqlalchemy", sources["evaluation"])
        self.assertNotIn("httpx", sources["evaluation"])
        for forbidden in ("sqlalchemy", "httpx", "subprocess"):
            self.assertNotIn(forbidden, sources["admission"])
            self.assertNotIn(forbidden, sources["window"])

    def test_window_clock_closes_even_when_clock_resolution_is_frozen(
        self,
    ) -> None:
        now = datetime.now(timezone.utc)
        clock = DeveloperShadowWindowClock(now=lambda: now)

        started = clock.open()
        closed = clock.close(started_at=started)

        self.assertEqual(closed.started_at, started)
        self.assertGreater(closed.ended_at, closed.started_at)
        self.assertGreaterEqual(closed.collected_at, closed.ended_at)

    def test_window_clock_rejects_naive_time(self) -> None:
        clock = DeveloperShadowWindowClock(
            now=lambda: datetime(2026, 8, 5)
        )

        with self.assertRaisesRegex(ValueError, "requires aware time"):
            clock.open()

    def test_preview_contract_accepts_complete_non_release_evidence(self) -> None:
        artifact = _artifact()

        self.assertEqual(
            artifact.artifact_version,
            "developer-shadow-preview-v2",
        )
        self.assertEqual(artifact.status, "passed")
        self.assertFalse(artifact.release_gate_credit)
        self.assertEqual(artifact.admission_profile, "developer_preview")
        self.assertTrue(artifact.configured_thinking)
        self.assertEqual(artifact.coverage.accepted, 20)

    def test_preview_policy_accepts_exact_thinking_model(self) -> None:
        golden = _golden(uuid.uuid4())
        candidate = _admission_candidate(golden, configured_thinking=True)

        result = DeveloperPreviewAdmissionPolicy().require(
            candidate,
            golden=golden,
        )

        self.assertEqual(result.admission_profile, "developer_preview")
        self.assertTrue(result.configured_thinking)

    def test_preview_policy_rejects_inactive_or_non_chat_model(self) -> None:
        golden = _golden(uuid.uuid4())
        for profile in (
            DeveloperShadowModelProfile(
                model_type="llm",
                configured_thinking=False,
                is_active=False,
            ),
            DeveloperShadowModelProfile(
                model_type="embedding",
                configured_thinking=False,
                is_active=True,
            ),
        ):
            candidate = _admission_candidate(
                golden,
                profile=profile,
            )
            with self.assertRaisesRegex(
                DeveloperPreviewAdmissionError,
                "developer_preview_model_admission_missing",
            ):
                DeveloperPreviewAdmissionPolicy().require(
                    candidate,
                    golden=golden,
                )

    def test_preview_policy_rejects_golden_binding_mismatch(self) -> None:
        golden = _golden(uuid.uuid4())
        candidate = _admission_candidate(golden)
        mismatched = golden.model_copy(
            update={"configuration_fingerprint": "f" * 64}
        )

        with self.assertRaisesRegex(
            DeveloperPreviewAdmissionError,
            "golden_admission_binding_mismatch",
        ):
            DeveloperPreviewAdmissionPolicy().require(
                candidate,
                golden=mismatched,
            )

    def test_preview_contract_rejects_controller_main_response(self) -> None:
        with self.assertRaises(ValidationError):
            _artifact(response_modes={"controller_v1": 20})

    def test_coverage_and_business_writes_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            DeveloperShadowCoverage(
                requested=20,
                accepted=20,
                enrolled=20,
                observed=19,
                shadow_valid=19,
                terminal=20,
                watermark_match=20,
                violation_count=0,
            )
        with self.assertRaises(ValidationError):
            DeveloperShadowBusinessWrites(
                memory_events=1,
                task_states=0,
                task_plan_versions=0,
                research_runs=0,
                shadow_audit_receipts=0,
                legacy_request_receipts=0,
            )

    def test_cli_bounds_require_isolated_loopback_and_20_to_50_turns(self) -> None:
        verifier = DeveloperShadowSourceVerifier()
        self.assertEqual(
            verifier._normalize_base_url("http://127.0.0.1:8081/"),
            "http://127.0.0.1:8081",
        )
        self.assertEqual(
            verifier._require_remote_ref("origin/dev"),
            "origin/dev",
        )
        for invalid in (
            "http://127.0.0.1:8080",
            "https://example.com:8081",
            "http://127.0.0.1:8081/api",
        ):
            with self.assertRaises(DeveloperShadowSourceError):
                verifier._normalize_base_url(invalid)
        for invalid_count in (19, 51):
            with self.assertRaises(ValidationError):
                DeveloperShadowPreviewCommand(
                    base_url="http://127.0.0.1:8081",
                    commit_sha=COMMIT,
                    remote_ref="origin/dev",
                    model_id=uuid.uuid4(),
                    golden_artifact="golden.json",
                    turn_count=invalid_count,
                )
        for invalid_ref in ("", "--verify", "origin/../dev", "origin/dev^{commit}"):
            with self.assertRaises(DeveloperShadowSourceError):
                verifier._require_remote_ref(invalid_ref)

    def test_request_ids_are_unique_and_bounded(self) -> None:
        values = DeveloperShadowHttpClient.new_request_ids(50)

        self.assertEqual(len(values), 50)
        self.assertEqual(len(set(values)), 50)
        self.assertTrue(all(len(value) <= 128 for value in values))

    def test_http_payload_uses_admitted_model_thinking_mode(self) -> None:
        payload = DeveloperShadowHttpClient.request_payload(
            prompt="safe prompt",
            user_id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            request_id="request-1",
            model_id=uuid.uuid4(),
            configured_thinking=True,
        )

        self.assertIs(payload["thinking_mode"], True)

    def test_http_response_uses_typed_legacy_request_identity(self) -> None:
        payload = {
            "type": "ai",
            "content": "ok",
            "custom_data": {
                "runtime_trace": {"request_id": "request-1"},
            },
        }

        self.assertEqual(
            DeveloperShadowHttpClient.parse_response_mode(
                payload,
                request_id="request-1",
            ),
            "legacy_runtime",
        )
        with self.assertRaises(DeveloperShadowHttpError):
            DeveloperShadowHttpClient.parse_response_mode(
                payload,
                request_id="request-2",
            )

    def test_golden_loader_requires_exact_passed_report(self) -> None:
        model_id = uuid.uuid4()
        source = GitSourceState(commit_sha=COMMIT, dirty_worktree=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "golden.json"
            path.write_text(
                _golden(model_id).model_dump_json(),
                encoding="utf-8",
            )
            loaded, digest = DeveloperShadowSourceVerifier._load_golden(
                path,
                source_state=source,
                model_id=model_id,
            )
            self.assertEqual(loaded.status, "passed")
            self.assertEqual(len(digest), 64)

            invalid_path = Path(directory) / "invalid.json"
            invalid = _golden(model_id).model_copy(
                update={"total_runtime_calls": 1}
            )
            invalid_path.write_text(
                invalid.model_dump_json(),
                encoding="utf-8",
            )
            with self.assertRaises(DeveloperShadowSourceError):
                DeveloperShadowSourceVerifier._load_golden(
                    invalid_path,
                    source_state=source,
                    model_id=model_id,
                )

    def test_artifact_leakage_check_rejects_raw_prompt(self) -> None:
        evaluator = DeveloperShadowPreviewEvaluator()
        evaluator.assert_no_raw_input_leakage(
            prompts=["private input"],
            payloads=[{"safe": "hash-only"}],
        )
        with self.assertRaises(DeveloperShadowEvaluationError):
            evaluator.assert_no_raw_input_leakage(
                prompts=["private input"],
                payloads=[json.loads('{"value": "private input"}')],
            )

    def test_window_projection_selects_only_registered_subject(self) -> None:
        evaluator = DeveloperShadowPreviewEvaluator()
        thread_id = uuid.uuid4()
        request_ids = ["request-1", "request-2"]
        keys = [
            shadow_observation_key_from_identity(
                thread_id=thread_id,
                request_id=request_id,
                controller_fingerprint=CONTROLLER,
            )
            for request_id in request_ids
        ]
        now = datetime.now(timezone.utc)
        read_request = ShadowGateReadRequest(
            commit_sha=COMMIT,
            controller_fingerprint=CONTROLLER,
            configuration_fingerprint=CONFIGURATION,
            prompt_version=CONTROLLER_PROMPT_VERSION,
            window_started_at=now - timedelta(minutes=1),
            window_ended_at=now,
            collected_at=now,
        )
        turns = [
            ShadowGateRawTurn(
                observation_key=key,
                enrolled_at=now - timedelta(seconds=1),
                journal_sequence_watermark=index,
            )
            for index, key in enumerate(keys, start=1)
        ]
        turns.append(
            ShadowGateRawTurn(
                observation_key="f" * 64,
                enrolled_at=now - timedelta(seconds=1),
                journal_sequence_watermark=3,
            )
        )

        selected = evaluator.select_request_scope(
            ShadowGateRawWindow(request=read_request, turns=turns),
            request_ids=request_ids,
            thread_id=thread_id,
            controller_fingerprint=CONTROLLER,
        )

        self.assertEqual(
            [turn.observation_key for turn in selected.turns],
            keys,
        )
        with self.assertRaises(DeveloperShadowEvaluationError):
            evaluator.select_request_scope(
                ShadowGateRawWindow(request=read_request, turns=turns[1:]),
                request_ids=request_ids,
                thread_id=thread_id,
                controller_fingerprint=CONTROLLER,
            )

    def test_shadow_read_contract_carries_optional_subject_scope(self) -> None:
        now = datetime.now(timezone.utc)
        request = ShadowGateReadRequest(
            commit_sha=COMMIT,
            controller_fingerprint=CONTROLLER,
            configuration_fingerprint=CONFIGURATION,
            prompt_version=CONTROLLER_PROMPT_VERSION,
            window_started_at=now - timedelta(minutes=1),
            window_ended_at=now,
            collected_at=now,
            thread_id=uuid.uuid4(),
            request_ids=["request-1", "request-2"],
        )

        self.assertEqual(len(request.request_ids), 2)
        self.assertIsNotNone(request.thread_id)


if __name__ == "__main__":
    unittest.main()
