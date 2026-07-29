from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.services.memory.contracts import (
    MEMORY_POLARITIES,
    MEMORY_SUBJECTS,
    MEMORY_TYPES,
    USER_STATE_CATEGORIES,
)
from app.services.memory.schema_registry import (
    is_canonical_state_key,
    schema_for,
)
from app.services.memory.write_contracts import (
    MemoryFactDraft,
    ResolvedMemoryFact,
)


_UNRESOLVED_VALUE_RE = re.compile(
    r"^(?:这个|那个|这些|那些|它|他|她|我的名字|我的信息|我的资料|"
    r"这件事|那件事|this|that|it|him|her|my name)$",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"[?？]|(?:什么|谁|哪个|哪些|是否|吗|呢)$|"
    r"\b(?:what|who|which|whether)\b",
    re.IGNORECASE,
)


class MemoryFactValidator:
    """Validate completeness; never reads or writes durable memory."""

    def reasons(self, draft: MemoryFactDraft) -> list[str]:
        reasons: list[str] = []
        if draft.category not in USER_STATE_CATEGORIES - {"short_term"}:
            reasons.append("not_long_term_category")
        if draft.durability != "long_term":
            reasons.append("durability_not_long_term")
        if not is_canonical_state_key(draft.state_key):
            reasons.append("invalid_state_key")
        spec = schema_for(draft.state_key)
        if spec is None:
            reasons.append("unregistered_state_key")
        elif spec.category != draft.category:
            reasons.append("state_key_category_mismatch")
        if draft.legacy_type not in MEMORY_TYPES - {"forget"}:
            reasons.append("invalid_legacy_type")
        if draft.legacy_subject not in MEMORY_SUBJECTS:
            reasons.append("invalid_legacy_subject")
        if draft.polarity not in MEMORY_POLARITIES:
            reasons.append("invalid_polarity")
        if not draft.summary or _QUESTION_RE.search(draft.summary):
            reasons.append("summary_not_assertive")
        if not draft.legacy_value:
            reasons.append("legacy_value_missing")
        if not draft.state_value and not draft.relation:
            reasons.append("structured_value_missing")
        if draft.unresolved_references:
            reasons.append("unresolved_reference")
        if any(
            _UNRESOLVED_VALUE_RE.fullmatch(value.strip())
            for value in _text_values([draft.state_value, draft.relation])
            if value.strip()
        ):
            reasons.append("referential_value_not_resolved")
        if draft.source.source_kind not in {
            "current_user_assertion",
            "prior_user_assertion",
        }:
            reasons.append("source_not_user_assertion")
        minimum = 0.80 if draft.extraction_method == "deterministic" else 0.90
        if draft.extraction_confidence < minimum:
            reasons.append("extraction_confidence_too_low")
        return list(dict.fromkeys(reasons))

    def resolve(self, draft: MemoryFactDraft) -> ResolvedMemoryFact:
        reasons = self.reasons(draft)
        if reasons:
            raise ValueError(
                "memory fact is not commit-ready: " + ", ".join(reasons)
            )
        return ResolvedMemoryFact(
            category=draft.category,
            state_key=draft.state_key,
            summary=draft.summary,
            state_value=draft.state_value,
            relation=draft.relation,
            use_when=draft.use_when,
            legacy_type=draft.legacy_type,
            legacy_subject=draft.legacy_subject,
            legacy_value=draft.legacy_value,
            polarity=draft.polarity,
            source=draft.source,
            extraction_method=draft.extraction_method,
            extraction_confidence=draft.extraction_confidence,
        )


def _text_values(values: Iterable[Any]) -> Iterable[str]:
    for value in values:
        if isinstance(value, dict):
            yield from _text_values(value.values())
        elif isinstance(value, (list, tuple, set)):
            yield from _text_values(value)
        elif isinstance(value, str):
            yield value
