from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal


Cardinality = Literal["single", "multi"]
ConflictPolicy = Literal[
    "replace_on_direct_assertion",
    "merge",
    "clarify",
]


@dataclass(frozen=True)
class MemorySchemaSpec:
    prefix: str
    category: str
    cardinality: Cardinality
    conflict_policy: ConflictPolicy
    sensitive: bool = False


_SPECS: tuple[MemorySchemaSpec, ...] = (
    MemorySchemaSpec(
        prefix="profile.name",
        category="profile",
        cardinality="single",
        conflict_policy="replace_on_direct_assertion",
    ),
    MemorySchemaSpec(
        prefix="profile.",
        category="profile",
        cardinality="single",
        conflict_policy="clarify",
    ),
    MemorySchemaSpec(
        prefix="preference.",
        category="preference",
        cardinality="multi",
        conflict_policy="merge",
    ),
    MemorySchemaSpec(
        prefix="relation.",
        category="relation",
        cardinality="multi",
        conflict_policy="clarify",
    ),
    MemorySchemaSpec(
        prefix="feedback.",
        category="feedback",
        cardinality="multi",
        conflict_policy="merge",
    ),
)

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")
_STATE_KEY_RE = re.compile(r"^[a-z][a-z0-9_.:-]{2,159}$")


def schema_for(state_key: str) -> MemorySchemaSpec | None:
    key = str(state_key or "").strip().lower()
    exact = next((spec for spec in _SPECS if spec.prefix == key), None)
    if exact is not None:
        return exact
    return next(
        (
            spec
            for spec in _SPECS
            if spec.prefix.endswith(".") and key.startswith(spec.prefix)
        ),
        None,
    )


def canonical_state_key(category: str, *parts: str) -> str:
    """Build an ASCII, stable key without leaking arbitrary fact text."""

    category_token = _ascii_token(category, fallback_prefix="category")
    tokens = [
        _ascii_token(part, fallback_prefix="v")
        for part in parts
        if str(part or "").strip()
    ]
    if not tokens:
        tokens = ["v_" + _digest(category_token)]
    return ".".join([category_token, *tokens])[:160].rstrip(".")


def is_canonical_state_key(
    state_key: str,
    *,
    category: str | None = None,
) -> bool:
    key = str(state_key or "").strip()
    if not _STATE_KEY_RE.fullmatch(key) or not key.isascii():
        return False
    return category is None or key.startswith(f"{category}.")


def _ascii_token(value: str, *, fallback_prefix: str) -> str:
    normalized = (
        str(value or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace(".", "_")
    )
    normalized = re.sub(r"[^a-z0-9_-]+", "_", normalized).strip("_-")
    if normalized and normalized[0].isalpha() and _TOKEN_RE.fullmatch(normalized):
        return normalized
    return f"{fallback_prefix}_{_digest(str(value or ''))}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
