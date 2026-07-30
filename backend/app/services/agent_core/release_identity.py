from __future__ import annotations

import re


class AgentReleaseIdentityError(RuntimeError):
    """Raised when an Agent deployment has no exact source identity."""


def require_release_commit_sha(value: object) -> str:
    commit_sha = str(value or "").strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit_sha) is None:
        raise AgentReleaseIdentityError(
            "agent_release_commit_sha_missing_or_invalid"
        )
    return commit_sha


__all__ = [
    "AgentReleaseIdentityError",
    "require_release_commit_sha",
]
