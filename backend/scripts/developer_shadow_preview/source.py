from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from app.services.agent_core.controller_golden_contracts import (
    ControllerGoldenReport,
)
from app.services.agent_core.evidence_source import (
    GitSourceState,
    GitSourceStateReader,
)
from app.services.agent_core.prompt_composer import CONTROLLER_PROMPT_VERSION
from scripts.developer_shadow_preview.contracts import (
    DeveloperShadowPreviewCommand,
)


class DeveloperShadowSourceError(RuntimeError):
    """Fail-closed source preflight error with a stable reason code."""


@dataclass(frozen=True)
class DeveloperShadowSourceProof:
    base_url: str
    remote_ref: str
    remote_commit_sha: str
    source_state: GitSourceState
    golden: ControllerGoldenReport
    golden_sha256: str


class DeveloperShadowSourceVerifier:
    """Bind one preview to local source, remote source, and Golden evidence."""

    def verify(
        self,
        command: DeveloperShadowPreviewCommand,
        *,
        repository_root: Path,
    ) -> DeveloperShadowSourceProof:
        base_url = self._normalize_base_url(command.base_url)
        remote_ref = self._require_remote_ref(command.remote_ref)
        source_state = GitSourceStateReader().require_release_state(
            repository_root,
            expected_commit_sha=command.commit_sha,
        )
        remote_commit = self._remote_commit(repository_root, remote_ref)
        if remote_commit != source_state.commit_sha:
            raise DeveloperShadowSourceError("remote_head_commit_mismatch")
        golden, golden_sha = self._load_golden(
            command.golden_artifact,
            source_state=source_state,
            model_id=command.model_id,
        )
        return DeveloperShadowSourceProof(
            base_url=base_url,
            remote_ref=remote_ref,
            remote_commit_sha=remote_commit,
            source_state=source_state,
            golden=golden,
            golden_sha256=golden_sha,
        )

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        candidate = value.strip().rstrip("/")
        parsed = urlsplit(candidate)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port is None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise DeveloperShadowSourceError(
                "isolated_loopback_base_url_required"
            )
        if parsed.port == 8080:
            raise DeveloperShadowSourceError(
                "shared_default_backend_port_forbidden"
            )
        return candidate

    @staticmethod
    def _require_remote_ref(value: str) -> str:
        candidate = value.strip()
        allowed = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789._/-"
        )
        if (
            not candidate
            or len(candidate) > 256
            or candidate.startswith("-")
            or ".." in candidate
            or any(char not in allowed for char in candidate)
        ):
            raise DeveloperShadowSourceError("remote_ref_invalid")
        return candidate

    @staticmethod
    def _remote_commit(repository_root: Path, remote_ref: str) -> str:
        try:
            completed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository_root),
                    "rev-parse",
                    "--verify",
                    f"{remote_ref}^{{commit}}",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeveloperShadowSourceError("remote_ref_unavailable") from exc
        commit = completed.stdout.strip().lower()
        if len(commit) != 40 or any(
            char not in "0123456789abcdef" for char in commit
        ):
            raise DeveloperShadowSourceError("remote_ref_invalid")
        return commit

    @staticmethod
    def _load_golden(
        path: str | Path,
        *,
        source_state: GitSourceState,
        model_id: UUID,
    ) -> tuple[ControllerGoldenReport, str]:
        try:
            raw = Path(path).read_bytes()
            report = ControllerGoldenReport.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            raise DeveloperShadowSourceError("golden_artifact_invalid") from exc
        if (
            report.status != "passed"
            or not report.live_model_evidence
            or report.source_dirty_worktree
            or report.commit_sha != source_state.commit_sha
            or report.model_id != model_id
            or report.prompt_version != CONTROLLER_PROMPT_VERSION
            or report.sample_count != 26
            or report.passed_count != 26
            or report.critical_passed != report.critical_count
            or report.safety_passed != report.safety_count
            or report.explicit_tool_count < 1
            or report.explicit_tool_passed / report.explicit_tool_count < 0.98
            or report.simple_tool_trigger_count != 0
            or report.total_runtime_calls != 0
        ):
            raise DeveloperShadowSourceError("golden_artifact_not_admitted")
        return report, hashlib.sha256(raw).hexdigest()


__all__ = [
    "DeveloperShadowSourceError",
    "DeveloperShadowSourceProof",
    "DeveloperShadowSourceVerifier",
]
