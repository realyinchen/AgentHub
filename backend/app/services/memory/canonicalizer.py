from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.services.memory.version_contracts import (
    CanonicalMemoryTarget,
    CanonicalMemoryFact,
    ForgetMemoryTargetProposal,
    MemoryAssertionProposal,
    MemoryCanonicalizationResult,
    MemoryTargetResolutionResult,
)
from app.services.memory.versioned_schema_registry import (
    VersionedMemorySchema,
    VersionedMemorySchemaRegistry,
)


_SELF_SUBJECTS = frozenset({"self", "user", "me", "myself", "我", "本人"})
_SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "secret_key",
        "token",
    }
)
_CREDENTIAL_TEXT_RE = re.compile(
    r"(?:\bsk-[a-z0-9_-]{12,}\b|"
    r"\bbearer\s+[a-z0-9._~+/=-]{12,}|"
    r"\b(?:api[_ -]?key|password|secret|token)\s*[:=]\s*\S{6,})",
    re.IGNORECASE,
)


class MemoryCanonicalizer:
    """Convert model assertions into system-owned canonical fact identities."""

    def __init__(
        self,
        registry: VersionedMemorySchemaRegistry | None = None,
    ) -> None:
        self._registry = registry or VersionedMemorySchemaRegistry()

    def canonicalize(
        self,
        assertions: list[MemoryAssertionProposal],
        *,
        source_text: str,
    ) -> MemoryCanonicalizationResult:
        if not assertions:
            return MemoryCanonicalizationResult(
                status="clarification_required",
                clarification_question="请说明希望我记住的完整事实。",
                reason_codes=["empty_assertion_batch"],
            )

        facts: list[CanonicalMemoryFact] = []
        for assertion in assertions:
            result = self._canonicalize_one(
                assertion,
                source_text=source_text,
            )
            if isinstance(result, MemoryCanonicalizationResult):
                return result
            facts.append(result)

        by_key: dict[str, set[str]] = {}
        for fact in facts:
            by_key.setdefault(fact.memory_key, set()).add(
                fact.canonical_hash
            )
        conflict = next(
            (
                memory_key
                for memory_key, hashes in by_key.items()
                if len(hashes) > 1
            ),
            "",
        )
        if conflict:
            return MemoryCanonicalizationResult(
                status="clarification_required",
                clarification_question=(
                    "同一事实出现了多个不同值，请直接说明最终希望保留的值。"
                ),
                reason_codes=["batch_memory_key_conflict", conflict],
            )

        unique = {
            (fact.memory_key, fact.canonical_hash): fact
            for fact in facts
        }
        return MemoryCanonicalizationResult(
            status="ready",
            facts=list(unique.values()),
            reason_codes=["system_canonicalization_completed"],
        )

    def resolve_targets(
        self,
        targets: list[ForgetMemoryTargetProposal],
        *,
        source_text: str,
    ) -> MemoryTargetResolutionResult:
        if not targets:
            return MemoryTargetResolutionResult(
                status="clarification_required",
                clarification_question="请说明希望忘记的具体事实。",
                reason_codes=["empty_forget_target_batch"],
            )
        resolved: list[CanonicalMemoryTarget] = []
        normalized_source = _normalize_text(source_text)
        for target in targets:
            schema = self._registry.resolve_predicate(target.predicate)
            if schema is None:
                return MemoryTargetResolutionResult(
                    status="clarification_required",
                    clarification_question=(
                        "我还不能确定你希望忘记哪一种长期事实。"
                    ),
                    reason_codes=["unknown_memory_predicate"],
                )
            subject = _normalize_text(target.subject).lower()
            if schema.self_subject_only and subject not in _SELF_SUBJECTS:
                return MemoryTargetResolutionResult(
                    status="clarification_required",
                    clarification_question=(
                        "请明确要忘记的是你的事实还是其他人的信息。"
                    ),
                    reason_codes=["subject_scope_ambiguous"],
                )
            evidence = _normalize_text(target.evidence_quote)
            if evidence.casefold() not in normalized_source.casefold():
                return MemoryTargetResolutionResult(
                    status="rejected",
                    reason_codes=["evidence_not_found_in_user_source"],
                )
            if (
                _contains_secret(target.identity)
                or _contains_secret(target.qualifiers)
                or _CREDENTIAL_TEXT_RE.search(evidence)
            ):
                return MemoryTargetResolutionResult(
                    status="rejected",
                    reason_codes=["secret_or_credential_forbidden"],
                )
            try:
                identity_value = _canonical_json_object(target.identity)
                qualifiers = _canonical_json_object(target.qualifiers)
            except ValueError:
                return MemoryTargetResolutionResult(
                    status="rejected",
                    reason_codes=["non_json_memory_target"],
                )
            missing_identity = _missing_fields(
                identity_value,
                schema.identity_value_fields,
            )
            missing_qualifiers = _missing_fields(
                qualifiers,
                schema.identity_qualifier_fields,
            )
            if schema.cardinality == "multi" and (
                missing_identity or missing_qualifiers
            ):
                fields = ", ".join(
                    [*missing_identity, *missing_qualifiers]
                )
                return MemoryTargetResolutionResult(
                    status="clarification_required",
                    clarification_question=(
                        f"还不能唯一确定要忘记的事实，请补充：{fields}。"
                    ),
                    reason_codes=["incomplete_forget_target"],
                )
            identity = _identity_payload(
                schema,
                identity_value,
                qualifiers,
            )
            resolved.append(
                CanonicalMemoryTarget(
                    schema_key=schema.schema_key,
                    memory_key=_memory_key(schema, identity),
                    evidence_quote=evidence,
                )
            )
        unique = {item.memory_key: item for item in resolved}
        return MemoryTargetResolutionResult(
            status="ready",
            targets=list(unique.values()),
            reason_codes=["system_target_resolution_completed"],
        )

    def _canonicalize_one(
        self,
        assertion: MemoryAssertionProposal,
        *,
        source_text: str,
    ) -> CanonicalMemoryFact | MemoryCanonicalizationResult:
        schema = self._registry.resolve_predicate(assertion.predicate)
        if schema is None:
            return _clarification(
                "我还不能确定这条信息属于哪一种长期事实，请换一种完整说法。",
                "unknown_memory_predicate",
            )

        subject = _normalize_text(assertion.subject).lower()
        if schema.self_subject_only and subject not in _SELF_SUBJECTS:
            return _clarification(
                "请明确这是关于你本人的事实，还是关于其他人的信息。",
                "subject_scope_ambiguous",
            )
        canonical_subject = "self" if schema.self_subject_only else subject

        evidence = _normalize_text(assertion.evidence_quote)
        normalized_source = _normalize_text(source_text)
        if evidence.casefold() not in normalized_source.casefold():
            return MemoryCanonicalizationResult(
                status="rejected",
                reason_codes=["evidence_not_found_in_user_source"],
            )
        if _contains_secret(assertion.value) or _contains_secret(
            assertion.qualifiers
        ) or _CREDENTIAL_TEXT_RE.search(evidence):
            return MemoryCanonicalizationResult(
                status="rejected",
                reason_codes=["secret_or_credential_forbidden"],
            )

        try:
            value = _canonical_json_object(assertion.value)
            qualifiers = _canonical_json_object(assertion.qualifiers)
        except ValueError:
            return MemoryCanonicalizationResult(
                status="rejected",
                reason_codes=["non_json_memory_value"],
            )

        missing_value = _missing_fields(
            value,
            schema.required_value_fields,
        )
        missing_qualifiers = _missing_fields(
            qualifiers,
            schema.required_qualifier_fields,
        )
        if missing_value or missing_qualifiers:
            fields = ", ".join([*missing_value, *missing_qualifiers])
            return _clarification(
                f"这条事实还缺少必要信息：{fields}。",
                "incomplete_canonical_fact",
            )
        if (
            schema.schema_key == "preference.entity"
            and str(value.get("polarity") or "").lower()
            not in {"like", "dislike", "avoid", "want", "neutral"}
        ):
            return _clarification(
                "请明确这是喜欢、不喜欢、想要还是避免。",
                "invalid_preference_polarity",
            )

        identity = _identity_payload(schema, value, qualifiers)
        memory_key = _memory_key(schema, identity)
        canonical_payload = {
            "schema_key": schema.schema_key,
            "schema_version": schema.version,
            "subject": canonical_subject,
            "value": value,
            "qualifiers": qualifiers,
        }
        canonical_hash = hashlib.sha256(
            _stable_json(canonical_payload).encode("utf-8")
        ).hexdigest()
        return CanonicalMemoryFact(
            schema_key=schema.schema_key,
            memory_key=memory_key,
            schema_version=schema.version,
            subject=canonical_subject,
            predicate=schema.schema_key,
            value=value,
            qualifiers=qualifiers,
            evidence_quote=evidence,
            canonical_hash=canonical_hash,
        )


def _clarification(
    question: str,
    reason: str,
) -> MemoryCanonicalizationResult:
    return MemoryCanonicalizationResult(
        status="clarification_required",
        clarification_question=question,
        reason_codes=[reason],
    )


def _identity_payload(
    schema: VersionedMemorySchema,
    value: dict[str, Any],
    qualifiers: dict[str, Any],
) -> dict[str, Any]:
    return {
        "value": {
            key: value[key]
            for key in schema.identity_value_fields
        },
        "qualifiers": {
            key: qualifiers[key]
            for key in schema.identity_qualifier_fields
        },
    }


def _memory_key(
    schema: VersionedMemorySchema,
    identity: dict[str, Any],
) -> str:
    if schema.cardinality == "single":
        return f"{schema.schema_key}:self"
    digest = hashlib.sha256(
        _stable_json(identity).encode("utf-8")
    ).hexdigest()[:32]
    return f"{schema.schema_key}:{digest}"


def _canonical_json_object(value: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key).strip().lower(): _canonical_json_value(child)
        for key, child in sorted(
            value.items(),
            key=lambda item: str(item[0]).lower(),
        )
    }


def _canonical_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, dict):
        return _canonical_json_object(value)
    raise ValueError("memory values must be JSON-compatible")


def _missing_fields(
    value: dict[str, Any],
    required: tuple[str, ...],
) -> list[str]:
    return [
        field
        for field in required
        if field not in value or not _has_value(value[field])
    ]


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).strip().lower() in _SECRET_KEYS:
                return True
            if _contains_secret(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return isinstance(value, str) and bool(_CREDENTIAL_TEXT_RE.search(value))


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
