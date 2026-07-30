from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import Field

from app.services.agent_core.contracts import AgentCoreModel


class EvidenceSourceStateError(RuntimeError):
    """Raised when release evidence cannot bind one clean Git source."""


class GitSourceState(AgentCoreModel):
    commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    dirty_worktree: bool


class GitSourceStateReader:
    """Read and validate Git source identity without running any gate."""

    def read(self, repository_root: str | Path) -> GitSourceState:
        root = Path(repository_root).resolve()
        commit_sha = self._git(
            root,
            "rev-parse",
            "--verify",
            "HEAD",
        ).strip().lower()
        dirty = bool(
            self._git(
                root,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ).strip()
        )
        try:
            return GitSourceState(
                commit_sha=commit_sha,
                dirty_worktree=dirty,
            )
        except ValueError as exc:
            raise EvidenceSourceStateError(
                "git_source_state_invalid"
            ) from exc

    def require_release_state(
        self,
        repository_root: str | Path,
        *,
        expected_commit_sha: str,
    ) -> GitSourceState:
        state = self.read(repository_root)
        if state.commit_sha != str(expected_commit_sha).lower():
            raise EvidenceSourceStateError(
                "git_source_commit_mismatch"
            )
        if state.dirty_worktree:
            raise EvidenceSourceStateError(
                "git_source_worktree_dirty"
            )
        return state

    @staticmethod
    def _git(root: Path, *arguments: str) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), *arguments],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except (
            OSError,
            subprocess.SubprocessError,
        ) as exc:
            raise EvidenceSourceStateError(
                "git_source_state_unavailable"
            ) from exc
        return completed.stdout


__all__ = [
    "EvidenceSourceStateError",
    "GitSourceState",
    "GitSourceStateReader",
]
