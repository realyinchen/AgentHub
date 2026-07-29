"""App-owned contract for ordinary book search state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BookSearchStatus = Literal[
    "ok",
    "empty_result",
    "timeout",
    "garbage",
    "hard_error",
    "loop_detected",
    "intent_blocked",
]

BOOK_SEARCH_STATUSES = frozenset(
    {
        "ok",
        "empty_result",
        "timeout",
        "garbage",
        "hard_error",
        "loop_detected",
        "intent_blocked",
    }
)

BOOK_SEARCH_NEXT_ACTION_HINTS: dict[BookSearchStatus, str] = {
    "ok": (
        "Use these candidates to answer. Do not call search_books again in this "
        "ordinary recommendation turn unless the user explicitly asked for another "
        "search or refinement."
    ),
    "empty_result": (
        "Do not repeat the same search in this turn. Recommend from retrieved "
        "memory and general book knowledge, or ask one focused follow-up if the "
        "request is too broad."
    ),
    "timeout": (
        "The search provider timed out. Do not retry in this ordinary turn. "
        "Answer with available context and mention that live search timed out."
    ),
    "garbage": (
        "The search provider returned unusable content. Do not retry in this "
        "ordinary turn. Answer with available context or ask for a narrower cue."
    ),
    "hard_error": (
        "The search provider failed. Do not retry in this ordinary turn. Answer "
        "with available context and avoid inventing source-specific ratings or links."
    ),
    "loop_detected": (
        "A search has already been attempted in this ordinary recommendation turn. "
        "Stop searching and produce the best answer from existing results, memory, "
        "and general knowledge."
    ),
    "intent_blocked": (
        "The user did not explicitly request book recommendations or book search. "
        "Do not recommend books in this turn. Answer only the user's stated "
        "question, and optionally offer concise follow-up questions the user may "
        "ask next."
    ),
}


def get_book_search_hint(status: BookSearchStatus) -> str:
    return BOOK_SEARCH_NEXT_ACTION_HINTS[status]


@dataclass(frozen=True)
class BookCandidateSearchResult:
    """Normalized result of one external ordinary book search call."""

    query: str
    provider_query: str
    status: BookSearchStatus
    candidates: list[dict] = field(default_factory=list)
    source: str = "external_search"
    next_action_hint: str = ""
    error: str | None = None
    duration_ms: int = 0

    @property
    def result_count(self) -> int:
        return len(self.candidates)
