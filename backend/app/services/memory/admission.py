from __future__ import annotations

from typing import Any

from app.services.memory.contracts import (
    INFORMATION_SCOPES,
    MEMORY_CANDIDATE_SOURCE_KINDS,
    MemoryAdmissionDecision,
    MemoryCandidate,
    MemoryEvent,
    normalize_memory_token,
    normalize_memory_value,
    validate_memory_token,
)


LONG_TERM_WRITABLE_MEMORY_TYPES = frozenset(
    {"state", "preference", "feedback", "reading_state", "entity", "correction"}
)
DISALLOWED_LONG_TERM_SOURCE_KINDS = frozenset(
    {
        "search_result",
        "research_evidence",
        "provider_raw",
        "thread_summary",
        "temporary_turn_state",
    }
)
BROAD_MEMORY_VALUES = frozenset(
    {
        "it",
        "this",
        "that",
        "thing",
        "things",
        "something",
        "anything",
        "unknown",
        "book",
        "books",
        "novel",
        "novels",
        "preference",
        "这些",
        "这个",
        "那个",
        "它",
        "某些",
        "一些",
        "书",
        "小说",
        "内容",
        "风格",
        "偏好",
        "喜欢",
        "不喜欢",
    }
)


class MemoryAdmissionError(ValueError):
    """Raised when a legacy write path expects a committed memory event."""

    def __init__(self, decision: MemoryAdmissionDecision) -> None:
        self.decision = decision
        super().__init__(
            f"memory admission {decision.decision}: {decision.reason or 'blocked'}"
        )


class MemoryAdmissionEngine:
    """App-owned gate that decides what may become long-term memory."""

    def admit(self, candidate: MemoryCandidate) -> MemoryAdmissionDecision:
        if candidate.scope != "long_term_memory":
            return self._decision(
                "reject",
                "non_long_term_scope",
                candidate,
                metadata={"scope": candidate.scope},
            )

        if candidate.type not in LONG_TERM_WRITABLE_MEMORY_TYPES:
            return self._decision(
                "reject",
                "unsupported_long_term_memory_type",
                candidate,
                metadata={"type": candidate.type},
            )

        if candidate.source_kind in DISALLOWED_LONG_TERM_SOURCE_KINDS:
            return self._decision(
                "reject",
                f"{candidate.source_kind}_cannot_enter_long_term_memory",
                candidate,
                metadata={"source_kind": candidate.source_kind},
            )

        if candidate.source_kind == "model_inference":
            return self._decision(
                "needs_confirmation",
                "model_inference_requires_user_confirmation",
                candidate,
                metadata={"source_kind": candidate.source_kind},
            )

        if candidate.source_kind == "user_message":
            precommit = candidate.metadata.get("precommit")
            required_gates = {
                "source_identified",
                "reference_resolved",
                "completeness_validated",
                "persistence_approved",
            }
            if not isinstance(precommit, dict) or not all(
                precommit.get(gate) is True for gate in required_gates
            ):
                return self._decision(
                    "reject",
                    "user_message_missing_precommit_proof",
                    candidate,
                    metadata={"required_gates": sorted(required_gates)},
                )

        value_reason = self._invalid_value_reason(candidate.value)
        if value_reason:
            return self._decision("reject", value_reason, candidate)

        if candidate.confidence < 0.25:
            return self._decision(
                "needs_confirmation",
                "candidate_confidence_too_low",
                candidate,
                metadata={"confidence": candidate.confidence},
            )

        return self._decision("allow", "user_expressed_long_term_memory", candidate)

    def _invalid_value_reason(self, value: str) -> str:
        text = normalize_memory_value(value)
        token = normalize_memory_token(text)
        if len(text) < 2:
            return "value_too_short"
        if token in BROAD_MEMORY_VALUES:
            return "value_too_broad"
        return ""

    def _decision(
        self,
        decision: str,
        reason: str,
        candidate: MemoryCandidate,
        *,
        warnings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryAdmissionDecision:
        return MemoryAdmissionDecision(
            decision=decision,
            reason=reason,
            candidate=candidate,
            warnings=warnings or [],
            metadata=metadata or {},
        )


def memory_event_to_candidate(
    event: MemoryEvent,
    *,
    scope: str = "long_term_memory",
    source_text: str = "",
    source_kind: str | None = None,
) -> MemoryCandidate:
    metadata = dict(event.metadata)
    admission_metadata = metadata.get("admission") or {}
    resolved_source_kind = (
        source_kind
        or admission_metadata.get("source_kind")
        or metadata.get("source_kind")
        or _source_kind_from_event_source(event.source)
    )
    return MemoryCandidate(
        user_id=event.user_id,
        thread_id=event.thread_id,
        type=event.type,
        subject=event.subject,
        value=event.value,
        polarity=event.polarity,
        confidence=event.confidence,
        scope=validate_memory_token("scope", scope, INFORMATION_SCOPES),
        source_text=source_text or admission_metadata.get("source_text", ""),
        source_kind=validate_memory_token(
            "source_kind",
            resolved_source_kind,
            MEMORY_CANDIDATE_SOURCE_KINDS,
        ),
        metadata=metadata,
    )


def _source_kind_from_event_source(source: str) -> str:
    if source == "manual":
        return "manual"
    if source == "tool":
        return "tool"
    return "user_message"
