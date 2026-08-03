from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pydantic import ValidationError

from app.services.agent_core.certification_contracts import (
    AGENT_CERTIFICATION_CONTRACT_VERSION,
    AGENT_PROBE_CASE_NAMES,
    AGENT_PROBE_REQUIRED_CASE_NAMES,
    AgentModeAdmission,
)
from app.services.agent_core.certification_evidence import (
    AgentCertificationEvidenceArtifact,
)

from app.services.agent_core.evidence_artifact import (
    EvidenceArtifactWriteError,
    EvidenceArtifactWriter,
)
from app.services.agent_core.evidence_source import (
    EvidenceSourceStateError,
    GitSourceState,
    GitSourceStateReader,
)
from app.services.agent_core.release_identity import (
    AgentReleaseIdentityError,
    require_release_commit_sha,
)
from scripts import verify_controller_capability_live as live_certification


class _FixtureGitSourceStateReader(GitSourceStateReader):
    def __init__(self, *, commit_sha: str, status: str) -> None:
        self._commit_sha = commit_sha
        self._status = status

    def _git(self, root: Path, *arguments: str) -> str:
        del root
        return (
            self._commit_sha + "\n"
            if arguments[0] == "rev-parse"
            else self._status
        )


class EvidenceArtifactTests(unittest.TestCase):
    def test_release_source_requires_exact_clean_commit(self) -> None:
        clean = _FixtureGitSourceStateReader(
            commit_sha="a" * 40,
            status="",
        )
        state = clean.require_release_state(
            ".",
            expected_commit_sha="a" * 40,
        )
        self.assertFalse(state.dirty_worktree)

        with self.assertRaisesRegex(
            EvidenceSourceStateError,
            "git_source_commit_mismatch",
        ):
            clean.require_release_state(
                ".",
                expected_commit_sha="b" * 40,
            )

        dirty = _FixtureGitSourceStateReader(
            commit_sha="a" * 40,
            status=" M backend/app/main.py\n",
        )
        with self.assertRaisesRegex(
            EvidenceSourceStateError,
            "git_source_worktree_dirty",
        ):
            dirty.require_release_state(
                ".",
                expected_commit_sha="a" * 40,
            )

    def test_evidence_writer_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            writer = EvidenceArtifactWriter()
            writer.write_json_new(output, {"status": "first"})
            first = output.read_text(encoding="utf-8")
            with self.assertRaisesRegex(
                EvidenceArtifactWriteError,
                "evidence_output_already_exists",
            ):
                writer.write_json_new(output, {"status": "second"})
            self.assertEqual(output.read_text(encoding="utf-8"), first)

    def test_agent_release_commit_is_exact_and_required(self) -> None:
        self.assertEqual(
            require_release_commit_sha("a" * 40),
            "a" * 40,
        )
        for invalid in (None, "", "A" * 40, "a" * 39):
            with self.subTest(invalid=invalid):
                with self.assertRaises(AgentReleaseIdentityError):
                    require_release_commit_sha(invalid)

    def test_certification_evidence_is_release_bound_and_redacted(
        self,
    ) -> None:
        certification_id = uuid4()
        model_id = uuid4()
        certification = SimpleNamespace(
            id=certification_id,
            model_id=model_id,
            source_commit_sha="c" * 40,
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            contract_version=AGENT_CERTIFICATION_CONTRACT_VERSION,
            certified=True,
            cases=[
                {
                    "name": name,
                    "required": True,
                    "passed": True,
                    "latency_ms": 1,
                    "error_message": "provider-secret-must-not-leak",
                }
                for name in AGENT_PROBE_CASE_NAMES
            ],
            failure_cases=[],
        )
        admission = AgentModeAdmission(
            admitted=True,
            certification_id=str(certification_id),
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            source_commit_sha="c" * 40,
        )

        artifact = AgentCertificationEvidenceArtifact.build(
            source_state=GitSourceState(
                commit_sha="c" * 40,
                dirty_worktree=False,
            ),
            certification=certification,
            admission=admission,
            generated_at=datetime.now(timezone.utc),
        )

        self.assertEqual(artifact.status, "passed")
        self.assertEqual(len(artifact.cases), 10)
        self.assertNotIn(
            "provider-secret-must-not-leak",
            artifact.model_dump_json(),
        )

    def test_certification_evidence_rejects_source_mismatch(
        self,
    ) -> None:
        certification_id = uuid4()
        certification = SimpleNamespace(
            id=certification_id,
            model_id=uuid4(),
            source_commit_sha="c" * 40,
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            contract_version=AGENT_CERTIFICATION_CONTRACT_VERSION,
            certified=True,
            cases=[
                {
                    "name": name,
                    "passed": True,
                    "latency_ms": 1,
                }
                for name in AGENT_PROBE_CASE_NAMES
            ],
            failure_cases=[],
        )
        admission = AgentModeAdmission(
            admitted=True,
            certification_id=str(certification_id),
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            source_commit_sha="c" * 40,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "source commit mismatch",
        ):
            AgentCertificationEvidenceArtifact.build(
                source_state=GitSourceState(
                    commit_sha="d" * 40,
                    dirty_worktree=False,
                ),
                certification=certification,
                admission=admission,
                generated_at=datetime.now(timezone.utc),
            )

    def test_failed_certification_produces_redacted_failed_artifact(
        self,
    ) -> None:
        certification_id = uuid4()
        failed_name = AGENT_PROBE_CASE_NAMES[0]
        certification = SimpleNamespace(
            id=certification_id,
            model_id=uuid4(),
            source_commit_sha="c" * 40,
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            contract_version=AGENT_CERTIFICATION_CONTRACT_VERSION,
            certified=False,
            cases=[
                {
                    "name": name,
                    "passed": name != failed_name,
                    "latency_ms": 1,
                    "error_message": "raw-provider-failure",
                }
                for name in AGENT_PROBE_CASE_NAMES
            ],
            failure_cases=[failed_name],
        )
        admission = AgentModeAdmission(
            admitted=False,
            certification_id=str(certification_id),
            reason="certification_failed",
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            source_commit_sha="c" * 40,
        )

        artifact = AgentCertificationEvidenceArtifact.build(
            source_state=GitSourceState(
                commit_sha="c" * 40,
                dirty_worktree=False,
            ),
            certification=certification,
            admission=admission,
            generated_at=datetime.now(timezone.utc),
        )

        self.assertEqual(artifact.status, "failed")
        self.assertEqual(artifact.failure_cases, [failed_name])
        self.assertNotIn(
            "raw-provider-failure",
            artifact.model_dump_json(),
        )

    def test_short_circuit_evidence_exposes_status_without_provider_text(
        self,
    ) -> None:
        certification_id = uuid4()
        failed_name = AGENT_PROBE_CASE_NAMES[0]
        certification = SimpleNamespace(
            id=certification_id,
            model_id=uuid4(),
            source_commit_sha="c" * 40,
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            contract_version=AGENT_CERTIFICATION_CONTRACT_VERSION,
            certified=False,
            cases=[
                {
                    "name": name,
                    "required": name in AGENT_PROBE_REQUIRED_CASE_NAMES,
                    "passed": False,
                    "latency_ms": 1 if name == failed_name else 0,
                    "error_message": "raw-provider-failure",
                    "observations": {
                        "executed": name == failed_name,
                        "error_category": "rate_limit",
                        **(
                            {}
                            if name == failed_name
                            else {"triggered_by": failed_name}
                        ),
                    },
                }
                for name in AGENT_PROBE_CASE_NAMES
            ],
            failure_cases=[
                name
                for name in AGENT_PROBE_CASE_NAMES
                if name in AGENT_PROBE_REQUIRED_CASE_NAMES
            ],
        )
        admission = AgentModeAdmission(
            admitted=False,
            certification_id=str(certification_id),
            reason="certification_failed",
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            source_commit_sha="c" * 40,
        )

        artifact = AgentCertificationEvidenceArtifact.build(
            source_state=GitSourceState(
                commit_sha="c" * 40,
                dirty_worktree=False,
            ),
            certification=certification,
            admission=admission,
            generated_at=datetime.now(timezone.utc),
        )

        self.assertTrue(artifact.cases[0].executed)
        self.assertTrue(all(not case.executed for case in artifact.cases[1:]))
        self.assertEqual(
            artifact.cases[1].short_circuited_by,
            failed_name,
        )
        self.assertNotIn("raw-provider-failure", artifact.model_dump_json())


class LiveCertificationPreflightTests(
    unittest.IsolatedAsyncioTestCase
):
    def test_cli_requires_explicit_model_id(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "sys.argv",
                [
                    "verify_controller_capability_live.py",
                    "--commit-sha",
                    "c" * 40,
                    "--output",
                    str(Path(directory) / "certification.json"),
                ],
            ),
            self.assertRaises(SystemExit),
        ):
            live_certification._arguments()

    async def test_existing_output_stops_before_database_or_provider(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "certification.json"
            output.write_text("existing", encoding="utf-8")
            arguments = SimpleNamespace(
                output=str(output),
                commit_sha="c" * 40,
                model_id=str(uuid4()),
                timeout_seconds=45,
            )
            with patch.object(
                live_certification,
                "_run",
                AsyncMock(),
            ) as run:
                with self.assertRaisesRegex(
                    EvidenceArtifactWriteError,
                    "evidence_output_already_exists",
                ):
                    await live_certification._main(arguments)
            run.assert_not_awaited()

    async def test_source_mismatch_stops_before_database_or_provider(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            arguments = SimpleNamespace(
                output=str(Path(directory) / "certification.json"),
                commit_sha="c" * 40,
                model_id=str(uuid4()),
                timeout_seconds=45,
            )
            with (
                patch.object(
                    live_certification.GitSourceStateReader,
                    "require_release_state",
                    side_effect=EvidenceSourceStateError(
                        "git_source_commit_mismatch"
                    ),
                ),
                patch.object(
                    live_certification,
                    "_run",
                    AsyncMock(),
                ) as run,
            ):
                with self.assertRaisesRegex(
                    EvidenceSourceStateError,
                    "git_source_commit_mismatch",
                ):
                    await live_certification._main(arguments)
            run.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
