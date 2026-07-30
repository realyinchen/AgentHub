"""Verify clean-source binding and write-once release evidence behavior."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_core.evidence_artifact import (
    EvidenceArtifactWriteError,
    EvidenceArtifactWriter,
)
from app.services.agent_core.evidence_source import (
    EvidenceSourceStateError,
    GitSourceStateReader,
)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    ).stdout.strip()


def _run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git(root, "init")
        _git(root, "config", "user.email", "evidence@example.invalid")
        _git(root, "config", "user.name", "Evidence Verifier")
        source = root / "source.txt"
        source.write_text("v1\n", encoding="utf-8")
        _git(root, "add", "source.txt")
        _git(root, "commit", "-m", "fixture source")
        commit_sha = _git(root, "rev-parse", "HEAD")

        reader = GitSourceStateReader()
        state = reader.require_release_state(
            root,
            expected_commit_sha=commit_sha,
        )
        if state.dirty_worktree:
            raise AssertionError("clean fixture was reported dirty")

        try:
            reader.require_release_state(
                root,
                expected_commit_sha="f" * 40,
            )
        except EvidenceSourceStateError as exc:
            if str(exc) != "git_source_commit_mismatch":
                raise
        else:
            raise AssertionError("commit mismatch was accepted")

        source.write_text("v2\n", encoding="utf-8")
        try:
            reader.require_release_state(
                root,
                expected_commit_sha=commit_sha,
            )
        except EvidenceSourceStateError as exc:
            if str(exc) != "git_source_worktree_dirty":
                raise
        else:
            raise AssertionError("dirty source was accepted")

        output = root / "evidence.json"
        writer = EvidenceArtifactWriter()
        writer.write_json_new(output, {"status": "first"})
        first = output.read_bytes()
        try:
            writer.write_json_new(output, {"status": "second"})
        except EvidenceArtifactWriteError as exc:
            if str(exc) != "evidence_output_already_exists":
                raise
        else:
            raise AssertionError("existing evidence was overwritten")
        if output.read_bytes() != first:
            raise AssertionError("write-once evidence changed")

    print("release evidence provenance verification passed")
    print("clean_head_binding=passed")
    print("commit_mismatch=blocked")
    print("dirty_worktree=blocked")
    print("existing_evidence_overwrite=blocked")


if __name__ == "__main__":
    _run()
