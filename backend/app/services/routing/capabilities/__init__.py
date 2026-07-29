"""Pure capability compilers for an accepted interaction decision.

Each compiler owns one capability family.  The package deliberately exposes
business-only ``ProposedAction`` values; execution context remains owned by
``SystemRuntime``.
"""

from __future__ import annotations

import re

from app.services.routing.interaction_contracts import ClauseDecision


_ACTION_KEY_TOKEN_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def scoped_action_key(
    base: str,
    clause: ClauseDecision,
    *,
    clause_index: int,
    clause_count: int,
) -> str:
    """Return a stable key that remains attributable in compound requests."""

    if clause_count == 1:
        return base
    clause_token = _ACTION_KEY_TOKEN_RE.sub(
        "_",
        str(clause.clause_id or "").strip(),
    ).strip("_")
    clause_token = clause_token or f"clause_{clause_index + 1}"
    return f"c{clause_index + 1}_{clause_token}__{base}"


def traced_reason(reason: str, clause: ClauseDecision) -> str:
    """Attach decision provenance without leaking it into tool arguments."""

    return f"{reason} [interaction_clause={clause.clause_id}]"


# Imports stay below the shared helpers so submodules can use them without a
# separate miscellaneous utility module.
from app.services.routing.capabilities.books import compile_book_actions
from app.services.routing.capabilities.conversation import (
    compile_conversation_actions,
)
from app.services.routing.capabilities.external import compile_external_actions
from app.services.routing.capabilities.memory import compile_memory_actions
from app.services.routing.capabilities.state import compile_state_actions


__all__ = [
    "compile_book_actions",
    "compile_conversation_actions",
    "compile_external_actions",
    "compile_memory_actions",
    "compile_state_actions",
    "scoped_action_key",
    "traced_reason",
]
